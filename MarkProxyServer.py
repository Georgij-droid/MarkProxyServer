from flask import Flask, request, Response
import requests
import json
from waitress import serve
import xml.etree.ElementTree as ET
import datetime
import os.path
import re
from typing import Tuple

#Класс для создания сервера
class ServerForRequest:
	#Конструктор класса
	def __init__(self, app, listen_endpoint, target_URL, body_type, mark_element, param_json=None, log_file=None, config=None):
		#Сохраняем полученные атрибуты
		self.app = app
		self._listen_endpoint = listen_endpoint
		self._target_URL = target_URL + listen_endpoint #целевой адрес состоит из URL и endpoint
		self.config = config
		self.body_type = body_type
		self.mark_element = mark_element
		self.param_json = param_json
		#сохраняем JSON с параметрами парсера (если он есть)
		if param_json is not None:
			self.parameters = json.loads(param_json) #сразу сохраняем как JSON
		self.log_file = log_file
		
		self._register_route() #вызываем метод для маршутизации сервера

	#Метод для создания сервера на конкретном endpoint
	def _register_route(self):
		endpoint_name = f"proxy_handler_{self._listen_endpoint.replace('/', '_')}" #указываем имя endpoint-а как "proxy_handler" + адрес эндпоинта ("/" заменены на "_")
		@self.app.route(self._listen_endpoint, methods=["POST"], endpoint=endpoint_name) #создаём приложение по полученному адресу
		def proxy_handler():
			return self._handle_request() #вызываем метод для обработки запроса

	#Метод для логирования
	def log(self, line: str):
		ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") #логируем дату-время
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

	#Космический парсер - метод для разделения марки на сегменты и удаления тех сегментов, которые нужно удалить
	@staticmethod
	def parser(mark: str, dict: str) -> Tuple[str, str]:
		json_dict = json.loads(dict) #поехали. Полученный JSON превращаем в словарь
		segm_result = [] #объявляем пустой массив - сюда будет писаться результат парсинга
		pre_parse_result = {"segments": segm_result} #объявляем словарь - из него получится итоговый результат парсинга
		if json_dict['need_changes'] == "N": #Если в конфиге указано, что изменения не нужны
			return mark, json.dumps({}) #возвращаем исходную марку и пустой словарь (словарь - это результат парсинга, а мы не парсили)
		elements_array = json_dict["segments"] #определяем массив с настройками сегментов
		new_mark = '' #new_mark - это результат парсинга. Начинаем с пустой строки
		#est_mark - это то, что осталось после парсинга. Начинаем с полученной марки (т.к. ещё не парсили)
		est_mark = mark.replace('&#x1D', chr(29)) #заменяем кракозябры на символ 29 - для парсинга
		while est_mark != '': #цикл будет продолжаться, пока есть неразобранный остаток марки (est_mark)
			element_num = 0 #начинаем с первого элемента массива
			#Цикл пройдёт по всем элементам массива
			for item in elements_array:
				segm_found = False #по умолчанию - сегмент не найден
				#сначала проверяем, есть ли в начале оставшейся марки символ-разделитель
				if est_mark[:1] != ' ' and est_mark[:1] != chr(29):
					#если разделителя нет
					segm_pre_symb = '' #символ перед сегментом - пустая строка
					pre_segm_code = est_mark[:len(item['id'])] #сравнивать с кодом сегмента будем столько символов, сколько символов в сравниваемом коде
				else:
					#если разделитель есть
					segm_pre_symb = est_mark[:1] #символ перед сегментом - первый символ
					pre_segm_code = est_mark[1:len(item['id']) + 1] #сравнивать с кодом сегмента будем столько символов, сколько символов в сравниваемом коде - но смещаем на 1 символ "вправо"
				#Проверяем, совпадают ли сравниваемые символы с текущим сегментом
				if pre_segm_code == item['id']:
					#если совпадают
					segm_arr_num = element_num #в этом случае номер элемента массива - это текущий номер
					segm_code = pre_segm_code #код сегмента - это сравниваемые символы
					segm_found = True #фиксируем, что сегмент найден
					break #и останавливаем цикл
				else:
					#если не совпадают
					#если номер элемента массива не достиг максимума
					if element_num + 1 < len(elements_array):
						element_num = element_num + 1 #увеличиваем номер элемента массива на 1 (для проверки следующего сегмента)
			#Если ничего не нашли, пройдя по всем элементам массива - возвращаем просто марку
			if not segm_found and new_mark=='' and element_num + 1 == len(elements_array):
				return mark, json.dumps({}) #возвращаем исходную марку и пустой словарь (словарь - это результат парсинга, а мы не парсили)

			#Убираем из оставшейся марки код сегмента
			est_mark = est_mark[len(segm_code):]
			#Логика для фиксированной длины сегмента
			if elements_array[element_num]['length_type'] == "F":
				segm_value = est_mark[len(segm_pre_symb):elements_array[element_num]['length'] + len(segm_pre_symb)]
			#Логика для переменной длины
			else:
				char_29_s = est_mark.find(chr(29)) #ищем символ 29
				space_s = est_mark.find(' ') #ищем пробел
				#Если не нашли ни одного разделителя - сегментом считается вся оставшаяся часть марки
				if char_29_s == -1 and space_s == -1:
					segm_value = est_mark
				#Если нашли - берём до разделителя
				else:
					if char_29_s == -1:
						segm_value = est_mark[len(segm_pre_symb):space_s] #если разделитель это пробел - берём все символы до пробела
					else:
						segm_value = est_mark[len(segm_pre_symb):char_29_s] #если разделитель это символ 29 - берём все символы до символа 29
			#Обязательно "обрезаем" est_mark - чтобы не попасть в бесконечный цикл
			est_mark = est_mark[len(segm_value) + len(segm_pre_symb):] #убираем из оставшейся марки столько символов справа, сколько символов в значении сегмента
			#Логика добавления элементов в "новую" марку (после парсинга)
			if elements_array[element_num].get('cut', 0) == 1:
				#если данный сегмента необходимо "отрезать" - не добавляем его в "новую" марку
				new_mark = new_mark
				segm_result.append({"segm_code": segm_code, "segm_value": segm_value, "add_to_result": False, "segm_pre_symb": segm_pre_symb})
			else:
				#в противном случае - добавляем (добавляется разделитель перед сегментом, код сегмента и его значение)
				new_mark = new_mark + segm_pre_symb + segm_code + segm_value
				segm_result.append({"segm_code": segm_code, "segm_value": segm_value, "add_to_result": True, "segm_pre_symb": segm_pre_symb})

		parse_result = json.dumps(pre_parse_result, ensure_ascii=False) #превращаем словарь с результатами парсинга в JSON

		#Заменяем пробел и символ 29 обратно на кракозябры
		new_mark = new_mark.replace(chr(29), '&#x1D')
		new_mark = new_mark.replace(' ', '&#x1D')
		
		return new_mark, parse_result #метод возвращает "новую марку" - если добрались до сюда. Также возвращаем словарь с результатом парсинга

	#Метод для обработки полученного запроса
	def _handle_request(self):
		listen_endpoint = self._listen_endpoint #фиксируем эндпоинт для отправки
		target_URL = self._target_URL #фиксируем URL для отправки

		#Если нужно - логируем факт получения нового запроса
		if self.log_file is not None:
			self.log("=== NEW REQUEST ===")

		#Проверяем, соответствует ли тело запроса ожидаемому типу
		if self.body_type == "json":
			#Если сервер ожидает JSON - проверяем, JSON ли он получил
			if not request.is_json:
				#Если нет - логируем факт ошибки и возвращаем ответ с кодом 400
				if self.log_file is not None:
					self.log("ERROR: Request is not JSON")
				return Response(
					"Content-Type must be application/json",
					status=400,
					content_type="text/plain"
				)
			#логика для JSON - удаление лишних сегментов, если это нужно
			json_data = json.loads(request.data) #обрабатываем полученный JSON
			#Ищем в нём марку. Ищем не фиксированное название элемента,
			#а то, которое получили при создании класса (из конфига)
			if self.mark_element in json_data:
				mark = json_data[f'{self.mark_element}'] #название элемента с маркой получаем извне
			else:
				mark = None #если не нашли элемент с таким названием - переменная mark принимает значение None
			#Если нужно - логируем оригинальный (полученный от клиента) запрос
			if self.log_file is not None:
				self.log("===ORIGINAL_REQUEST")
				#Если получен JSON
				if self.body_type == 'json':
					try:
						json_data = json.loads(request.data)
						self.log(json.dumps(json_data, ensure_ascii = False)) #логируем JSON
					except:
						self.log(request.data.decode('utf-8')) #если ошибка при разборе JSON - логируем "как есть"
				else:
					self.log(request.data.decode('utf-8')) #XML сразу логируем "как есть"
			#Если марка была найдена
			if mark is not None:
				json_data[self.mark_element] = ServerForRequest.parser(mark, self.param_json)[0] #меняем значение марки на результат парсинга (могут быть убраны "лишние" сегменты)
			new_data = json.dumps(json_data) #сохраняем изменённые данные для отправки изменённого запроса
			#Логирование изменённого запроса в Хотту
			if self.log_file is not None:
				if mark is not None:
					self.log("===PARSE_RESULT") #если парсили марку - логируем результат парсинга
					self.log(ServerForRequest.parser(mark, self.param_json)[1]) #получаем его из парсера
				self.log("===CHANGED REQUEST") 
				self.log(json.dumps(json_data, ensure_ascii = False)) #логируем изменённый запрос
		#Логика для XML
		elif self.body_type == "xml":
			xml_data = request.data.decode('utf-8') #декодируем XML для работы с ним
			#Если нужно - логируем полученный (оригинальный) запрос
			if self.log_file is not None:
				self.log("===ORIGINAL_REQUEST")
				xml_data_for_log = re.sub(r'>\s+<', '><', xml_data.strip()) #Из XML регулярными выражениями убираем пробелы между элементами
				self.log(xml_data_for_log) #логируем изменённый XML
			if not self.is_XML(xml_data):
				#Если получен не XML
				if self.log_file is not None:
					self.log("ERROR: Request is not XML") #При необходимости логируем ошибку
				#И возвращаем ответ с кодом 400
				return Response(
					"Content-Type must be application/xml",
					status=400,
					content_type="text/plain"
				)
			#логика для XML - удаление лишних сегментов, если это нужно
			root = ET.fromstring(xml_data)
			mark_element = root.find(f'.//{self.mark_element}') #ищем элемент с названием, которое получили извне
			parse_result_json = ''
			if mark_element is not None:
				mark = mark_element.text
				mark_element.text = ServerForRequest.parser(mark, self.param_json)[0]
				parse_result_json = ServerForRequest.parser(mark, self.param_json)[1]
			xml_data = ET.tostring(root, encoding='unicode', method='xml', xml_declaration=True)
			new_data = xml_data.encode('utf-8')
			#Логирование изменённого запроса
			if self.log_file is not None:
				#Если был парсинг - логируем его результат
				if parse_result_json != '':
					self.log("===PARSE_RESULT")
					self.log(parse_result_json)
				self.log("===CHANGED REQUEST")
				xml_data_for_log = re.sub(r'>\s+<', '><', xml_data.strip()) #Из XML регулярными выражениями убираем пробелы между элементами
				self.log(xml_data_for_log) #логируем изменённый XML

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
			content_type=response.headers.get("Content-Type", "application/json"))

class ConfigHandler:
	#Объявляем константы для сервера по умолчанию (если не удалось получить параметры из XML-конфигурации)
	DEFAULT_ENDPOINT = "/integration/request/check_mark_info"
	DEFAULT_TARGET_URL = "http://10.254.3.8:8820"
	DEFAULT_PARAM_JSON = '{"need_changes":"Y","segments":[{"id":"01","length_type":"F","length":14,"cut":0},{"id":"11","length_type":"F","length":6,"cut":0},{"id":"21","length_type":"V","length":0,"cut":0},{"id":"91","length_type":"F","length":4,"cut":1},{"id":"92","length_type":"F","length":88,"cut":1},{"id":"93","length_type":"F","length":4,"cut":1},{"id":"3103","length_type":"F","length":6,"cut":1}]}'
	DEFAULT_BODY_TYPE = "xml"
	DEFAULT_LOG_FILE = "log_xml.txt"
	DEFAULT_MARK_PATH = "mark" #это константа не для сервера. Это путь к элементу с маркой по умолчанию.
	DEFAULT_IP = "127.0.0.1" #параметры для адреса прокси по умолчанию (IP и порт)
	DEFAULT_PORT = 24100

	def __init__(self, app):
		self.app = app
		self.servers=[] #атрибут для сохранения созданных серверов в виде списка
		self.tree = self.load_XML_from_file('XMLConfig_for_proxy.xml') #при создании экземпляра класса получаем данные из XML
		self.start_servers() #создаём сервера

	#Метод для получения XML из файла
	def load_XML_from_file(self, file_path):
		#Проверяем, есть ли файл по адресу
		if os.path.isfile(file_path):
			#Если файл найден, пробуем распарсить его как XML
			try:
				tree = ET.parse(file_path) #парсим
				return tree #возвращаем распарсенный XML
			except:
				return None #если не удалось распарсить - возвращаем ничто
		#если файла нет по адресу
		else:
			return None #в этом случае возвращаем ничто

	#Метод для получения названия элемента с маркой из конфига
	def get_mark_element_num(self, path):
		tree = self.tree #берём XML из конструктора класса
		#Если XML нет - берём название элемента с маркой по умолчанию
		if tree is None:
			return self.DEFAULT_MARK_PATH
		#Если XML есть - парсим
		else:
			#root = tree.getroot() #определяем корневой элемент в XML
			#Если не удалось найти марку - берём значение по умолчанию
			if tree.find(path) == None:
				return self.DEFAULT_MARK_PATH
			#Если удалось - берём найденное значение
			else:
				return tree.find(path).text

	def start_servers(self):
		tree = self.tree #берём XML из конструктора класса
		#если XML нет - создаём сервер с параметрами по умолчанию
		if tree is None:
			server = ServerForRequest(
				app=self.app,
				listen_endpoint=self.DEFAULT_ENDPOINT,
				target_URL=self.DEFAULT_TARGET_URL,
				param_json = self.DEFAULT_PARAM_JSON,
				body_type=self.DEFAULT_BODY_TYPE,
				mark_element=self.DEFAULT_MARK_PATH,
				log_file=self.DEFAULT_LOG_FILE
			)
			self.servers.append(server) #сохраняем созданный сервер - чтобы он не "помер"
		#если XML есть - создаём сервера по конфигу
		else:
			root = tree.getroot() #определяем корневой элемент в XML
			i = 1 #начинаем с первой группы элементов Server
			for child in root:
				#для каждой группы элементов Server создаём свой сервер с заданными параметрами
				if child.tag == 'Server':
					self.parse_config(i, tree) #создаём с помощью специального метода
					i = i + 1

	#Метод для получения из конфига параметров сокета - IP и порта
	def get_socket(self):
		tree = self.tree #берём XML из конструктора класса
		if tree is None:
			return self.DEFAULT_IP, self.DEFAULT_PORT
		root = tree.getroot() #определяем корневой элемент в XML
		IP_in_config = 'IP' #как называется элемент с IP
		port_in_config = "port" #как называется элемент с портом
		#есть ли в XML элемент с IP
		if root.find(IP_in_config) != None:
			IP = root.find(IP_in_config).text #если есть - фиксируем его значение
		else:
			IP = self.DEFAULT_IP #если нет - берём значение по умолчанию
		#есть ли в XML элемент с портом
		if root.find(port_in_config) != None:
			port = root.find(port_in_config).text #если есть - фиксируем его значение
		else:
			port = self.DEFAULT_PORT #если нет - берём значение по умолчанию
		return IP, port #возвращаем IP и порт

	#Метод для получения из XML-конфигурации параметров для сервера и оздания самих серверов
	def parse_config(self, num, XML=None):
		tree = XML #фиксируем входящую XML
		root = tree.getroot() #определяем корневой элемент
		xpath = f'.//Server[{num}]' #создаём XPath-выражение (для поиска нужной группы элементов Server)
		mark_element_path = f'.//Server[{num}]/mark_element' #создаём XPath-выражение (для поиска элемента с маркой)
		mark_element = self.get_mark_element_num(mark_element_path) #обращаемся к методу для поиска марки
		target = tree.find(xpath) #ищем через XPath группу элементов Server с нужным номером
		#Если удалось найти Server с нужным номером
		if target != None:
			#Определяем параметры для сервера
			logging = target.find('Logging') #необходимость логирования
			listen_endpoint = str(target.find('ListenEndpoint').text) #endpoint
			target_URL = str(target.find('TargetURL').text) #URL конечного сервера
			body_type = str(target.find('BodyType').text) #тип данных в теле - JSON или XML
			if logging.text == "On": #Если логирование включено
				log_file = str(target.find('LogFile').text) + ".txt" #определяем имя файла для логов
			else:
				log_file = None #если логирование выключено - не передаём имя файла для логов
			dict_segm = {} #JSON начинается с пустого значения
			need_changes = str(target.find('.//NeedChanges').text) #находим в конфиге необходимость изменений в марке (для парсера)
			segm_data = [] #объявляем массив сегментов - в начале пустой
			dict_segm = {"need_changes": need_changes, "segments": segm_data} #создаём словарь для передачи парсеру (в нём будут параметры для сервера)
			#Начинаем поиск данных по сегментам
			for child in target:
				#Находим группу элементов Segments
				if child.tag == 'Segments':
					for child2 in child:
						#Находим группу элемнетов SegmentsForParser
						if child2.tag == 'SegmentsForParser':
							#По дочерним элементам ищем
							for child3 in child2:
								if child3.tag == 'SegmentForParser':
									Id = str(child3.find('Id').text) #находим Id сегмента
									LengthType = str(child3.find('LengthType').text) #находим тип сегмента (фиксированный или переменный)
									Length = int(child3.find('Length').text) #находим длину сегмента
									Cut = int(child3.find('Cut').text) #находим признак необходимости удаления
									segm_data.append({"cut": Cut, "id": Id, "length": Length, "length_type": LengthType}) #находим длину сегмента
			#преобразовываем словарь в JSON (для передачи парсеру)
			result_json = json.dumps(dict_segm, ensure_ascii=False)
			#Получив всё необходимое - создаём сервер с заданными настройками
			server = ServerForRequest(
				app=self.app, #Приложение получаем извне класса (входящий параметр)
				listen_endpoint=listen_endpoint, #listen_endpoint (и все прочие параметры) берём из XML
				target_URL=target_URL, #аналогично listen_endpoint
				body_type=body_type, #аналогично listen_endpoint
				mark_element=mark_element,
				param_json=result_json, #JSON используем тот, который сами сгенерировали - из данных XML
				log_file=log_file #log_file берём тоже из XML
				)
			self.servers.append(server) #сохраняем созданный сервер - чтобы он не "помер"
		#Если не удалось найти Server с нужным номером
		else:
			#В этом случае создаём сервер с параметрами по умолчанию
			server = ServerForRequest(
				app=self.app,
				listen_endpoint=self.DEFAULT_ENDPOINT,
				target_URL=self.DEFAULT_TARGET_URL,
				param_json = self.DEFAULT_PARAM_JSON,
				body_type=self.DEFAULT_BODY_TYPE,
				mark_element=self.DEFAULT_MARK_PATH,
				log_file=self.DEFAULT_LOG_FILE
			)
			self.servers.append(server) #сохраняем созданный сервер - чтобы он не "помер"

#Создаём приложение
app = Flask(__name__)

#Запуск приложения
if __name__ == "__main__":
	config = ConfigHandler(app) #создаём экземпляр класса, который получает конфиг и создаёт серверы
	IP = config.get_socket()[0] #получаем IP из конфига
	port = config.get_socket()[1] #получаем порт из конфига
	print("Server started at " + str(IP) + ":" + str(port)) #инфолог о запуске сервера
	serve(app, host=IP, port=port, threads=8) #создаём сервер