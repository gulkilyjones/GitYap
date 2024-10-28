# begin template/python3/http_handler.py ; marker comment, please do not remove

import os
import re
import json
import shutil
import urllib.parse
from datetime import datetime
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from typing import List, Tuple

import html
import http.server
import subprocess
import time
import random
import string

# Import from local modules
from config import SCRIPT_TYPES, INTERPRETER_MAP, MIME_TYPES
from commit_files import commit_text_files

class CustomHTTPRequestHandler(SimpleHTTPRequestHandler):
	static_files_initialized = False  # Class variable to track initialization

	@classmethod
	def setup_static_files(cls, directory):
		"""Setup static files by copying them from template to static directories"""
		if cls.static_files_initialized:
			return

		# Create static directories if they don't exist
		static_dirs = ['css', 'js']
		for dir_name in static_dirs:
			static_dir = Path(directory) / dir_name
			template_dir = Path(directory) / 'template' / dir_name

			# Create directory if it doesn't exist
			static_dir.mkdir(parents=True, exist_ok=True)

			# Copy all files from template directory to static directory
			if template_dir.exists():
				for file in template_dir.glob('*.*'):
					dest_file = static_dir / file.name
					if not dest_file.exists():  # Only copy if file doesn't exist
						shutil.copy2(file, dest_file)
						print(f"Copied {file} to {dest_file}")

		cls.static_files_initialized = True

	def __init__(self, *args, **kwargs):
		self.directory = os.getcwd()  # Set default directory
		super().__init__(*args, directory=self.directory)

	def do_GET(self):
		"""Handle GET requests with improved channel validation"""
		if self.path.startswith('/css/'):
			self.serve_static_file(self.path[1:])
		elif self.path.startswith('/js/'):
			self.serve_static_file(self.path[1:])
		elif self.path in ['/', '/index.html']:
			self.ensure_index_html()
			self.serve_static_file('index.html')
		elif self.path == '/log.html':
			self.generate_and_serve_report()
		elif self.path.startswith('/chat/'):
			# Extract and validate channel name
			parts = self.path.split('/')
			if len(parts) != 3:
				self.send_error(404, "Invalid channel URL")
				return

			channel = parts[2]
			if channel.endswith('.html'):
				channel = channel[:-5]  # Remove .html extension

			# Validate channel name
			if not self.is_valid_channel_name(channel):
				self.send_error(400, "Invalid channel name")
				return

			self.generate_and_serve_chat(channel)
		elif self.path == '/chat.html':
			self.generate_and_serve_chat('general')
		elif self.path.endswith('.txt'):
			self.serve_text_file_as_html()
		else:
			self.send_error(404, "File not found")

	def do_POST(self):
		"""Handle POST requests"""
		# Parse URL and query parameters
		parsed_path = urllib.parse.urlparse(self.path)
		path = parsed_path.path

		# Handle post to both /post and /chat.html
		if path in ['/post', '/chat.html']:
			self.handle_chat_post()
		else:
			self.send_error(405, "Method Not Allowed")

	def handle_chat_post(self):
		"""Handle POST request for chat messages"""
		try:
			content_length = int(self.headers.get('Content-Length', 0))
			if content_length > 1024 * 1024:  # 1MB limit
				self.send_error(413, "Request entity too large")
				return

			content_type = self.headers.get('Content-Type', '')
			print(f"Received Content-Type: {content_type}")  # Debug log

			# Handle both application/json and form submissions
			if 'application/json' in content_type:
				# JSON data
				post_data = self.rfile.read(content_length).decode('utf-8')
				data = json.loads(post_data)
			elif 'application/x-www-form-urlencoded' in content_type:
				# Form data
				post_data = self.rfile.read(content_length).decode('utf-8')
				form_data = urllib.parse.parse_qs(post_data)
				data = {
					'content': form_data.get('content', [''])[0],
					'author': form_data.get('author', [''])[0],
					'tags': form_data.get('tags', [''])[0].split(),
					'channel': form_data.get('channel', ['general'])[0],
					'reply_to': form_data.get('reply_to', [''])[0]
				}
			else:
				self.send_error(400, f"Invalid content type: {content_type}. Expected application/json or application/x-www-form-urlencoded")
				return

			# Validate required fields
			if not data.get('content', '').strip():
				self.send_error(400, "Message content is required")
				return

			# Sanitize and validate input
			author = html.escape(data.get('author', '').strip())[:50]
			content = html.escape(data.get('content', '').strip())[:5000]
			tags = [html.escape(tag.strip())[:30] for tag in data.get('tags', [])][:10]
			channel = html.escape(data.get('channel', 'general').strip())

			# Validate channel name
			if not self.is_valid_channel_name(channel):
				self.send_error(400, "Invalid channel name")
				return

			# Create message directory if it doesn't exist
			message_dir = os.path.join(self.directory, 'message', channel)
			os.makedirs(message_dir, exist_ok=True)

			# Generate timestamp and filename
			timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
			filename = f"{timestamp}.txt"
			filepath = os.path.join(message_dir, filename)

			# Write message to file
			with open(filepath, 'w', encoding='utf-8') as f:
				f.write(f"Author: {author}\n")
				f.write(f"Channel: {channel}\n\n")
				f.write(content)
				if tags:
					f.write(f"\n\n{' '.join(tags)}")

			# Initialize and commit to git repository for this channel
			channel_repo_path = os.path.join(message_dir)
			try:
				if not os.path.exists(channel_repo_path):
					os.makedirs(channel_repo_path, exist_ok=True)

				# Initialize git repo if needed and commit the new message
				if commit_text_files(channel_repo_path):
					print(f"Committed message to git repository for channel: {channel}")
				else:
					print(f"Failed to commit message to git repository for channel: {channel}")
			except Exception as e:
				print(f"Error handling git operations for channel {channel}: {str(e)}")

			# Force regenerate the chat page for this channel
			chat_file = f'chat_{channel}.html'
			if os.path.exists(chat_file):
				os.remove(chat_file)  # Remove existing file to force regeneration
			self.run_script('chat.html', '--channel', channel)

			# Redirect back to the chat page
			self.send_response(303)  # 303 See Other
			channel_path = f"/chat/{channel}.html"
			self.send_header('Location', channel_path)
			self.end_headers()

		except json.JSONDecodeError as e:
			print(f"JSON decode error: {str(e)}")  # Debug log
			self.send_error(400, "Bad Request: Invalid JSON")
		except Exception as e:
			print(f"Error in handle_chat_post: {str(e)}")  # Debug log
			self.send_error(500, str(e))

	def generate_and_serve_chat(self, channel='general'):
		"""Generate and serve the chat page for a specific channel"""
		output_file = f'chat_{channel}.html'

		# Force regenerate the file
		if os.path.exists(output_file):
			os.remove(output_file)

		self.run_script('chat.html', '--channel', channel)

		# Verify the file exists before serving
		if not os.path.exists(output_file):
			print(f"Error: Failed to generate {output_file}")
			self.send_error(500, "Failed to generate chat page")
			return

		self.serve_static_file(output_file)

	def is_valid_channel_name(self, channel):
		"""Validate channel name to prevent directory traversal and invalid names"""
		# Only allow alphanumeric characters, hyphens, and underscores
		return bool(re.match(r'^[a-zA-Z0-9_-]+$', channel))

	def trigger_github_update(self):
		"""Trigger GitHub update and run the corresponding script"""
		self.send_response(200)
		self.send_header('Content-type', 'text/html')
		self.end_headers()
		self.wfile.write(b"Update triggered successfully")
		self.run_script('github_update')

	def save_message(self, author: str, message: str):
		"""Save a chat message to a file"""
		timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
		title = self.generate_title(message)
		filename = f"{timestamp}_{title}.txt"

		message_dir = os.path.join(self.directory, 'message')
		os.makedirs(message_dir, exist_ok=True)

		filepath = os.path.join(message_dir, filename)
		with open(filepath, 'w', encoding='utf-8') as f:
			f.write(f"{message}\n\nAuthor: {author}")

	def generate_title(self, message: str) -> str:
		"""Generate a title for the message file"""
		if not message:
			return ''.join(random.choices(string.ascii_lowercase, k=10))

		words = message.split()[:5]
		title = '_'.join(words)
		safe_title = ''.join(c for c in title if c.isalnum() or c in ['_', '-'])
		return safe_title

	def generate_and_serve_report(self):
		"""Generate and serve the log report"""
		self.run_script_if_needed('log.html', 'log.html')
		self.serve_static_file('log.html')

	def generate_and_serve_chat(self, channel='general'):
		"""Generate and serve the chat page for a specific channel"""
		output_file = f'chat_{channel}.html'
		self.run_script_if_needed(output_file, 'chat.html', '--channel', channel)
		self.serve_static_file(output_file)

	def run_script_if_needed(self, output_filename: str, script_name: str, *args):
		"""Run a script if the output file doesn't exist or is outdated"""
		output_filepath = os.path.join(self.directory, output_filename)
		if not os.path.exists(output_filepath) or \
		   time.time() - os.path.getmtime(output_filepath) > 60:
			print(f"Generating {output_filename}...")
			self.run_script(script_name, *args)

	def run_script(self, script_name: str, *args):
		"""Run a script with the appropriate interpreter and arguments"""
		found_scripts = self.find_scripts(script_name)

		if not found_scripts:
			print(f"No scripts found for {script_name}")
			return

		for script_path, script_type in found_scripts:
			interpreter = INTERPRETER_MAP.get(script_type)
			if interpreter:
				cmd = [interpreter, script_path]
				if args:  # Add any additional arguments
					cmd.extend(str(arg) for arg in args)
				subprocess.run(cmd, cwd=self.directory)

	def find_scripts(self, script_name: str) -> List[Tuple[str, str]]:
		"""Find all scripts matching the given name"""
		found_scripts = []
		for template_dir in os.listdir(os.path.join(self.directory, 'template')):
			for script_type in SCRIPT_TYPES:
				script_path = os.path.join(self.directory, 'template', template_dir, f"{script_name}.{script_type}")
				if os.path.exists(script_path):
					found_scripts.append((script_path, script_type))
		return found_scripts

	def serve_text_file_as_html(self):
		"""Serve a text file as HTML"""
		path = os.path.join(self.directory, self.path[1:])
		try:
			with open(path, 'r', encoding='utf-8') as f:
				content = f.read()

			self.send_response(200)
			self.send_header("Content-type", "text/html; charset=utf-8")
			self.end_headers()

			escaped_content = html.escape(content)
			html_content = self.generate_html_content(os.path.basename(path), escaped_content)
			self.wfile.write(html_content.encode('utf-8'))
		except IOError:
			self.send_error(404, "File not found")

	def ensure_index_html(self):
		"""Ensure index.html exists in the home directory"""
		home_index = os.path.join(self.directory, 'index.html')
		if not os.path.exists(home_index):
			template_index = os.path.join(self.directory, 'template', 'html', 'index.html')
			if os.path.exists(template_index):
				with open(template_index, 'r', encoding='utf-8') as src:
					content = src.read()
				with open(home_index, 'w', encoding='utf-8') as dst:
					dst.write(content)
				print(f"Created index.html in home directory")

	def generate_html_content(self, title: str, content: str) -> str:
		"""Generate HTML content for displaying text files"""
		return f"""
		<!DOCTYPE html>
		<html lang="en">
		<head>
			<meta charset="UTF-8">
			<meta name="viewport" content="width=device-width, initial-scale=1.0">
			<title>{title}</title>
			<style>
			body {{ font-family: Arial, sans-serif; line-height: 1.6; padding: 20px; }}
			pre {{ background-color: #f4f4f4; padding: 15px; border-radius: 5px; white-space: pre-wrap; word-wrap: break-word; }}
			</style>
		</head>
		<body>
			<h1>{title}</h1>
			<pre>{content}</pre>
		</body>
		</html>
		"""

	def serve_static_file(self, path: str):
		"""Serve a static file"""
		file_path = os.path.join(self.directory, path)

		# If file doesn't exist in root directory, check template directory
		if not os.path.isfile(file_path):
			template_path = os.path.join(self.directory, 'template', path)
			if os.path.isfile(template_path):
				file_path = template_path

		if os.path.isfile(file_path):
			try:
				with open(file_path, 'rb') as f:
					content = f.read()
				content_type = self.get_content_type(file_path)
				self.send_response(200)
				self.send_header('Content-type', content_type)
				self.send_header('Cache-Control', 'public, max-age=3600')  # Cache for 1 hour
				self.end_headers()
				self.wfile.write(content)
			except Exception as e:
				print(f"Error serving {file_path}: {e}")
				self.send_error(500, f"Internal server error: {str(e)}")
		else:
			self.send_error(404, f"File not found: {path}")

	def get_content_type(self, file_path: str) -> str:
		"""Get the content type for a file"""
		ext = os.path.splitext(file_path)[1][1:].lower()
		return MIME_TYPES.get(ext, 'application/octet-stream')

# end http_handler.py ; marker comment, please do not remove