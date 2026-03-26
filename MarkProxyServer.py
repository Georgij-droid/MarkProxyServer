from flask import Flask, request, Response
import requests
import json
from waitress import serve
import xml.etree.ElementTree as ET
import datetime
import os.path
import re


class ServerForRequest:
	def __init__(self, app, listen_endpoint, target_URL, body_type, param_json=None, log_file=None, config=None):
		self.app = app
		self._listen_endpoint = listen_endpoint
		self._target_URL = target_URL + listen_endpoint
		self.config = config
		self.body_type = body_type
		self.param_json = param_json
		if param_json is not None:
			self.parameters = json.loads(param_json)
		self.log_file = log_file
		
		self._register_route()

	def _register_route(self):
		endpoint_name = f"proxy_handler_{self._listen_endpoint.replace('/', '_')}"
		@self.app.route(self._listen_endpoint, methods=["POST"], endpoint=endpoint_name)
		def proxy_handler():
			return self._handle_request()

	#Метод для логирования
	def log(self, line: str):
		ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
		with open(self.log_file, "a", encoding="utf-8") as f:
			f.write(f"[{ts}] {line}\n")

	#Метод для проверки, является ли содержимое XML
	@staticmethod
	def is_XML(data):
		try:
			ET.fromstring(data)
			return True
		except ET.ParseError:
			return False

	#Метод для разделения марки на сегменты и удаления тех сегментов, которые нужно удалить
	def parser(self, mark: str, dict: str)->str:
		json_dict = json.loads(dict)
		if json_dict['need_changes'] == "N":
			return mark
		#mark = mark.replace('&#x1D', chr(29)) #заменяем кракозябры на пробел - для парсинга
		elements_array = json_dict["segments"]
		element_num = 1 #начинаем с первого элемента. Подсчёт элементов нужен для понимания, что процесс завершён
		new_mark = ''
		est_mark = mark.replace('&#x1D', chr(29)) #заменяем кракозябры на пробел - для парсинга
		for item in elements_array:
			segm_found = False #инициализация переменной
			segm_pre_symb = ''
			segm_code = est_mark[:len(item['id'])]
			if est_mark[:1] == chr(29):
				segm_pre_symb = chr(29)
				segm_code = est_mark[1:len(item['id']) + 1]

			if est_mark[:1] == ' ':
				segm_pre_symb = ' '
				segm_code = est_mark[1:len(item['id']) + 1]

			
			if segm_code == item['id']:
				segm_found = True
				#Если длина сегмента указана фиксированной
				if segm_pre_symb != '':
					est_mark = est_mark[1 + len(item['id']):]
				else:
					est_mark = est_mark[len(item['id']):]
				if item['length_type'] == "F":
					segm_value = est_mark[:item['length']]
				#Если сегмент указан с переменной длиной
				else:
					#Ищем разделитель - символ 29 или пробел
					char_29_s = est_mark.find(chr(29))
					space_s = est_mark.find(' ')
					#Если не нашли ни одного разделителя - сегментом считается вся оставшаяся часть марки
					if char_29_s == -1 and space_s == -1:
						segm_value = est_mark
						new_mark = new_mark + segm_pre_symb + segm_code + segm_value
						return new_mark
					#Если нашли - берём до разделителя
					else:
						if char_29_s == -1:
							segm_value = est_mark[:space_s]
						else:
							segm_value = est_mark[:char_29_s]
				#Если сегмент надо убрать - не добавляем его в итоговую марку
				if item['cut'] != 1:
					new_mark = new_mark + segm_pre_symb + segm_code + segm_value
				est_mark = est_mark[len(segm_value):]
						
			#Если не удалось найти ни одного сегмента - выдаём марку в неизменном виде	
			if segm_found ==False and element_num == len(elements_array):
				return mark

		new_mark = new_mark.replace(chr(29), '&#x1D')
		new_mark = new_mark.replace(' ', '&#x1D')
		return(new_mark)

	def _handle_request(self):
		listen_endpoint = self._listen_endpoint
		target_URL = self._target_URL

		if self.log_file is not None:
			self.log("=== NEW REQUEST ===")

		#Проверяем, соответствует ли тело запроса ожидаемому типу
		if self.body_type == "json":
			if not request.is_json:
				if self.log_file is not None:
					self.log("ERROR: Request is not JSON")
				return Response(
					"Content-Type must be application/json",
					status=400,
					content_type="text/plain"
				)
			#логика для JSON - удаление лишних сегментов, если это нужно
			json_data = json.loads(request.data)
			if 'uit' in json_data:
				mark = json_data['uit'] #марка - это uit, а не uitu (uitu - это короб)
			else:
				mark = None
			if self.log_file is not None:
				self.log("===ORIGINAL_REQUEST")
				if self.body_type == 'json':
					try:
						json_data = json.loads(request.data)
						self.log(json.dumps(json_data, ensure_ascii = False))
					except:
						self.log(request.data.decode('utf-8'))
				else:
					self.log(request.data.decode('utf-8'))
			if mark is not None:
				json_data['uit'] = self.parser(mark, self.param_json)
			new_data = json.dumps(json_data)
			#Логирование изменённого запроса в Хотту
			if self.log_file is not None:
				self.log("===CHANGED REQUEST")
				#self.log(self._target_URL)
				self.log(json.dumps(json_data, ensure_ascii = False))
		elif self.body_type == "xml":
			xml_data = request.data.decode('utf-8')
			if self.log_file is not None:
				self.log("===ORIGINAL_REQUEST")
				xml_data_for_log = re.sub(r'>\s+<', '><', xml_data.strip())
				self.log(xml_data_for_log)
			if not self.is_XML(xml_data):
				if self.log_file is not None:
					self.log("ERROR: Request is not XML")
				return Response(
					"Content-Type must be application/xml",
					status=400,
					content_type="text/plain"
				)
			#логика для XML - удаление лишних сегментов, если это нужно
			root = ET.fromstring(xml_data)
			mark_element = root.find('.//mark')
			#print(self.param_json)
			if mark_element is not None:
				mark = mark_element.text
				mark_element.text = self.parser(mark, self.param_json)
			xml_data = ET.tostring(root, encoding='unicode', method='xml', xml_declaration=True)
			new_data = xml_data.encode('utf-8')
			#xml_data2 = new_data.decode('utf-8')
			#Логирование изменённого запроса в Хотту
			if self.log_file is not None:
				self.log("===CHANGED REQUEST")
				xml_data_for_log = re.sub(r'>\s+<', '><', xml_data.strip())
				self.log(xml_data_for_log)

		#Отправка на целевой сервер
		response = requests.post(
			self._target_URL,
			data=new_data, 
			headers=dict(request.headers),
			timeout=30
		)

		#Логирование ответа
		if self.log_file is not None:
			self.log("===RESPONSE===")
			#self.log(response.headers)
			self.log(response.content.decode('utf-8'))

		#Возврат ответа клиенту
		return Response(
			response.content,
			status=response.status_code,
			content_type=response.headers.get("Content-Type", "application/json")) #проверить, всегда ли JSON в ответе - возможно, XML

class ConfigHandler:
	def __init__(self, app):
		self.app = app
		self.servers=[] #атрибут для сохранения созданных серверов в виде списка
		self.load_XML_from_file('XMLConfig_for_proxy.xml')

	def load_XML_from_file(self, file_path):
		if os.path.isfile(file_path):
			try:
				tree = ET.parse(file_path)
				root = tree.getroot() #определяем корневой элемент в XML
				i = 1 #начинаем с первой группы элементов Server
				for child in root:
					if child.tag == 'Server':
						self.parse_config(i, tree)
						i = i + 1
			except:
				server = ServerForRequest(
					app=self.app,
					listen_endpoint="/integration/request/check_mark_info",
					target_URL="http://10.254.3.8:8820",
					param_json = '{"need_changes":"Y","segments":[{"id":"01","length_type":"F","length":14,"cut":0},{"id":"11","length_type":"F","length":6,"cut":0},{"id":"21","length_type":"V","length":0,"cut":0},{"id":"91","length_type":"F","length":6,"cut":1},{"id":"92","length_type":"F","length":6,"cut":1},{"id":"93","length_type":"F","length":6,"cut":1},{"id":"3103","length_type":"F","length":6,"cut":1}]}',
					body_type="xml",
					log_file="log_xml.txt"
				)
				self.servers.append(server) #сохраняем созданный сервер - чтобы он не "помер"
		else:
			server = ServerForRequest(
				app=self.app,
				listen_endpoint="/integration/request/check_mark_info",
				target_URL="http://10.254.3.8:8820",
				param_json = '{"need_changes":"Y","segments":[{"id":"01","length_type":"F","length":14,"cut":0},{"id":"11","length_type":"F","length":6,"cut":0},{"id":"21","length_type":"V","length":0,"cut":0},{"id":"91","length_type":"F","length":6,"cut":1},{"id":"92","length_type":"F","length":6,"cut":1},{"id":"93","length_type":"F","length":6,"cut":1},{"id":"3103","length_type":"F","length":6,"cut":1}]}',
				body_type="xml",
				log_file="log_xml.txt"
			)
			self.servers.append(server) #сохраняем созданный сервер - чтобы он не "помер"

	def parse_config(self, num, XML=None):
		tree = XML
		root = tree.getroot() #определяем корневой элемент
		xpath = f'.//Server[{num}]'
		target = tree.find(xpath)
		if target != None:
			#Определяем параметры для сервера
			logging = target.find('Logging') #еобходимость логирования
			listen_endpoint = str(target.find('ListenEndpoint').text) #endpoint
			target_URL = str(target.find('TargetURL').text) #URL конечного сервера
			body_type = str(target.find('BodyType').text) #тип данных в теле - JSON или XML
			if logging.text == "On": #Если логирование включено
				log_file = str(target.find('LogFile').text) + ".txt" #определяем имя файла для логов
			else:
				log_file = None
			dict_segm = {} #JSON начинается с пустого значения
			need_changes = str(target.find('.//NeedChanges').text)
			segm_data = []
			#dict_segm.append({"need_changes": need_changes, "segments": segm_data})
			dict_segm = {"need_changes": need_changes, "segments": segm_data}
			for child in target:
				if child.tag == 'Segments':
					for child2 in child:
						if child2.tag == 'SegmentsForParser':
							for child3 in child2:
								if child3.tag == 'SegmentForParser':
									Id = str(child3.find('Id').text)
									LengthType = str(child3.find('LengthType').text)
									Length = int(child3.find('Length').text)
									Cut = int(child3.find('Cut').text)
									segm_data.append({"cut": Cut, "id": Id, "length": Length, "length_type": LengthType})
			result_json = json.dumps(dict_segm, ensure_ascii=False)
			#Получив всё необходимое - создаём сервер с заданными настройками
			server = ServerForRequest(
				app=self.app, #Приложение получаем извне класса (входящий параметр)
				listen_endpoint=listen_endpoint, #listen_endpoint (и все прочие параметры) берём из XML
				target_URL=target_URL, #аналогично listen_endpoint
				body_type=body_type, #аналогично listen_endpoint
				param_json=result_json, #JSON используем тот, который сами сгенерировали - из данных XML
				log_file=log_file #log_file берём тоже из XML
				)
			self.servers.append(server) #сохраняем созданный сервер - чтобы он не "помер"
		else:
			server = ServerForRequest(
				app=self.app,
				listen_endpoint="/integration/request/check_mark_info",
				target_URL="http://10.254.3.8:8820",
				param_json = '{"need_changes":"Y","segments":[{"id":"01","length_type":"F","length":14,"cut":0},{"id":"11","length_type":"F","length":6,"cut":0},{"id":"21","length_type":"V","length":0,"cut":0},{"id":"91","length_type":"F","length":6,"cut":1},{"id":"92","length_type":"F","length":6,"cut":1},{"id":"93","length_type":"F","length":6,"cut":1},{"id":"3103","length_type":"F","length":6,"cut":1}]}',
				body_type="xml",
				log_file="log_xml.txt"
			)
			self.servers.append(server) #сохраняем созданный сервер - чтобы он не "помер"


app = Flask(__name__)

#Запуск приложения
if __name__ == "__main__":
	IP = "127.0.0.1"
	#IP = "10.139.4.167"
	port = 24100
	print("Server started at " + str(IP) + ":" + str(port))
	config = ConfigHandler(app)
	serve(app, host=IP, port=port, threads=8)