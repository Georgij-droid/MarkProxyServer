from flask import Flask, request, Response
import requests
import json
from waitress import serve
import xml.etree.ElementTree as ET
import datetime


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
		elements_array = json_dict["segments"]
		new_mark = ''
		est_mark = mark
		for item in elements_array:
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
			if segm_found ==False:
				return mark

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
			mark = json_data['uitu']
			if self.log_file is not None:
				self.log("===ORIGINAL_REQUEST")
				self.log(request.data.decode('utf-8'))
			json_data['uitu'] = self.parser(mark, self.param_json)
			new_data = json.dumps(json_data)
			#Логирование изменённого запроса в Хотту
			if self.log_file is not None:
				self.log("===CHANGED REQUEST")
				#self.log(self._target_URL)
				self.log(json_data)
		elif self.body_type == "xml":
			xml_data = request.data.decode('utf-8')
			if self.log_file is not None:
				self.log("===ORIGINAL_REQUEST")
				self.log(xml_data)
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
			mark = mark_element.text
			mark_element.text = self.parser(mark, self.param_json)
			xml_data = ET.tostring(root, encoding='unicode', method='xml', xml_declaration=True)
			new_data = xml_data.encode('utf-8')
			#Логирование изменённого запроса в Хотту
			if self.log_file is not None:
				self.log("===CHANGED REQUEST")
				#self.log(self._target_URL)
				self.log(xml_data)

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
			self.log(response.content)

		#Возврат ответа клиенту
		return Response(
			response.content,
			status=response.status_code,
			content_type=response.headers.get("Content-Type", "application/json")) #проверить, всегда ли JSON в ответе - возможно, XML


app = Flask(__name__)

test_server = ServerForRequest(
	app=app,
	listen_endpoint="/integration/request/mark",
	target_URL="http://10.254.3.8:8820",
	body_type="json",
	param_json = '{"need_changes":"Y","segments":[{"id":"01","length_type":"F","length":14,"cut":0},{"id":"11","length_type":"F","length":6,"cut":0},{"id":"21","length_type":"V","length":0,"cut":0},{"id":"91","length_type":"F","length":6,"cut":1},{"id":"92","length_type":"F","length":6,"cut":1},{"id":"93","length_type":"F","length":6,"cut":1},{"id":"3103","length_type":"F","length":6,"cut":1}]}',
	log_file="log.txt"
)

test_server2 = ServerForRequest(
	app=app,
	listen_endpoint="/integration/request/check_mark_info",
	target_URL="http://10.254.3.8:8820",
	param_json = '{"need_changes":"Y","segments":[{"id":"01","length_type":"F","length":14,"cut":0},{"id":"11","length_type":"F","length":6,"cut":0},{"id":"21","length_type":"V","length":0,"cut":0},{"id":"91","length_type":"F","length":6,"cut":1},{"id":"92","length_type":"F","length":6,"cut":1},{"id":"93","length_type":"F","length":6,"cut":1},{"id":"3103","length_type":"F","length":6,"cut":1}]}',
	body_type="xml",
	log_file="log_xml.txt")

#Запуск приложения
if __name__ == "__main__":
	IP = "10.139.4.167"
	port = 24100
	print("Server started at " + str(IP) + ":" + str(port))
	serve(app, host=IP, port=port, threads=8)