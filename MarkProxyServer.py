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
		self._target_URL = target_URL
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

	#Метод для удаления из марки "лишних" сегментов
	def cut_segm(self, mark, segm: str, length):
		idx = mark.find(segm)
		if idx == -1:
			return mark
		#Убрать из марки код сегмента и значение, остальное оставить


	#@app.route(self._target_URL, methods=["POST"])
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
		elif self.body_type == "xml":
			xml_data = request.data.decode('utf-8')
			if not self.is_XML(xml_data):
				if self.log_file is not None:
					self.log("ERROR: Request is not XML")
				return Response(
					"Content-Type must be application/xml",
					status=400,
					content_type="text/plain"
				)
				#логика для XML - удаление лишних сегментов, если это нужно

		if self.log_file is not None:
			self.log("===ORIGINAL_REQUEST")
			self.log(request.data)

		#Отправка на целевой сервер
		response = requests.post(
			self._target_URL,
			data=request.data, #здесь поправить - отправка изменённого запроса!
			headers=dict(request.headers),
			timeout=30
		)

		#Возврат ответа клиенту
		return Response(
			response.content,
			status=response.status_code,
			content_type=response.headers.get("Content-Type", "application/json")) #проверить, всегда ли JSON в ответе - возможно, XML


app = Flask(__name__)

test_server = ServerForRequest(
	app=app,
	listen_endpoint="/integration/request/mark",
	target_URL="http://10.254.3.8:8820/integration/request/mark",
	body_type="json",
	param_json = '{"need_changes":"Y","segments":[{"id":"01","length_type":"F","length":14,"cut":0},{"id":"11","length_type":"F","length":6,"cut":0},{"id":"21","length_type":"V","length":0,"cut":1},{"id":"91","length_type":"F","length":6,"cut":1},{"id":"92","length_type":"F","length":6,"cut":1},{"id":"93","length_type":"F","length":6,"cut":1},{"id":"3103","length_type":"F","length":6,"cut":1}]}',
	log_file="log.txt"
)

test_server2 = ServerForRequest(
	app=app,
	listen_endpoint="/integration/request/check_mark_info",
	target_URL="http://10.254.3.8:8820/integration/request/mark",
	param_json = '{"need_changes":"Y","segments":[{"id":"01","length_type":"F","length":14,"cut":0},{"id":"11","length_type":"F","length":6,"cut":0},{"id":"21","length_type":"V","length":0,"cut":1},{"id":"91","length_type":"F","length":6,"cut":1},{"id":"92","length_type":"F","length":6,"cut":1},{"id":"93","length_type":"F","length":6,"cut":1},{"id":"3103","length_type":"F","length":6,"cut":1}]}',
	body_type="xml")

#Запуск приложения
if __name__ == "__main__":
	print("Server started at " + str("127.0.0.1") + ":" + str(6500))
	serve(app, host="127.0.0.1", port=6500, threads=8)