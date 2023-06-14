#!/usr/bin/env python
import argparse
import logging
import subprocess
import toml
import time
import os
import signal
from http import HTTPStatus
from multiprocessing import Process

import sys
from traceback import print_exc

import socket
from socketserver import TCPServer, StreamRequestHandler
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs

DEBUG = '--debug' in sys.argv

logger = logging.getLogger('selfhosted-docs')
hooks_dir = os.path.dirname(os.path.abspath(__file__))
projects_dir = os.path.dirname(hooks_dir)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(self.path[2:])
        params = {key: value[0] for key, value in params.items()}
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write("{}".format(params).encode('utf-8'))
        try:
            process_request(**params)
        except Exception as e:
            self.wfile.write('Exception: {}'.format(e).encode('utf-8') + b"\r\n")
            sys.exit(0)
        self.wfile.write(b"<html><head><title>Finish.</title></head>")
        # sys.exit(0)


class Server(TCPServer):
    # The constant would be better initialized by a systemd module
    SYSTEMD_FIRST_SOCKET_FD = 3

    def __init__(self, server_address, handler_cls):
        # Invoke base but omit bind/listen steps (performed by systemd activation!)
        TCPServer.__init__(
            self, server_address, handler_cls, bind_and_activate=False)
        # Override socket
        self.socket = socket.fromfd(
            self.SYSTEMD_FIRST_SOCKET_FD, self.address_family, self.socket_type)


def print_status_code(status: HTTPStatus):
    print('Status: {} {}'.format(status.value, status.name.replace('_', ' ').title()))


class Settings(object):
    def __init__(self, path=os.path.join(projects_dir, 'config.toml')):
        self._data = toml.load(open(path))

    def get_project(self, name):
        for project in self._data['projects']:
            if project['name'] == name:
                return project

    @property
    def key(self):
        return self._data['settings']['key']


class SelfhostedDocsException(Exception):
    status = HTTPStatus.INTERNAL_SERVER_ERROR
    message = ''

    def __init__(self, status: HTTPStatus = None, message: str = None):
        self.status = status or self.status
        self.message = message or self.message

    def cgi_error(self):
        print_status_code(self.status)
        print()
        print('({}) {}: {}'.format(self.status.value, self.__class__.__name__, self.message or 'Not message supplied'))


class OriginalException(SelfhostedDocsException):
    def __init__(self, exception: Exception, status: HTTPStatus = None):
        self.status = status or self.status
        self.exception = exception

    def cgi_error(self):
        print_status_code(self.status)
        print()
        if DEBUG:
            print('<h1></h1>'.format(self.exception))
            print('<pre>')
            print_exc()
            print('</pre>')
        else:
            print('Internal Error.')


class MissingParameterException(SelfhostedDocsException):
    status = HTTPStatus.BAD_REQUEST

    def __init__(self, parameter: str):
        super(MissingParameterException, self).__init__(self.status, 'Parameter name: {}'.format(parameter))


class InvalidKeyException(SelfhostedDocsException):
    status = HTTPStatus.BAD_REQUEST

    def __init__(self):
        super(InvalidKeyException, self).__init__(self.status, 'Invalid key')


def check_execution_success(cmd, cwd, env=None):
    p = subprocess.Popen(cmd, cwd=cwd, stderr=subprocess.PIPE, env=env)
    stdout, stderr = p.communicate()
    if p.returncode:
        logger.error('%i return code on "%s" command. Stderr: %s', p.returncode, ' '.join(cmd), stderr)


def execute_venv(cmd, cwd, venv):
    env = os.environ.copy()
    env['PATH'] = '{}/bin:{}'.format(venv, env.get('PATH', ''))
    env['VIRTUAL_ENV'] = venv
    return check_execution_success(cmd, cwd, env)


def reload(project_name: str):
    repo_directory = os.path.join(projects_dir, project_name)
    docs_directory = os.path.join(repo_directory, 'docs')
    venv_directory = os.path.join(repo_directory, '.venv')
    if not os.path.lexists(repo_directory):
        check_execution_success(['git', 'clone', settings.get_project(project_name)['url']], projects_dir)
    else:
        check_execution_success(['git', 'config', '--global', 'user.email', 'docs@nekmo.org'], repo_directory)
        check_execution_success(['git', 'config', '--global', 'user.name', 'Nekmo docs'], repo_directory)
        check_execution_success(['git', 'pull'], repo_directory)
    if not os.path.lexists(venv_directory):
        check_execution_success(['virtualenv', '.venv'], repo_directory)
    try:
        execute_venv(['pip', 'install', '-r', 'py3-requirements.txt'], repo_directory, venv_directory)
        execute_venv(['pip', 'install', '-r', 'requirements-dev.txt'], repo_directory, venv_directory)
        execute_venv(['make', 'html'], docs_directory, venv_directory)
    except Exception as e:
        print(e)
    os.kill(os.getppid(), signal.SIGTERM)


def cgi_management(**arguments):
    import cgi
    print("Content-Type: text/html")
    repo_name = arguments.get('repo_name')
    key = arguments.get('key')
    if not repo_name:
        raise MissingParameterException('repo_name')
    if not key:
        raise MissingParameterException('key')
    if key != settings.key:
        raise InvalidKeyException()
    print("")
    print("Starting...")
    os.system('{}/reload.py reload \'{}\'&'.format(hooks_dir, repo_name))
    print("Success")
    # sys.exit(0)


def process_request(**arguments):
    repo_name = arguments.get('repo_name')
    key = arguments.get('key')
    if not repo_name:
        raise MissingParameterException('repo_name')
    if not key:
        raise MissingParameterException('key')
    if key != settings.key:
        raise InvalidKeyException()
    p = Process(target=reload, args=(repo_name,))
    p.start()


def cgi_start():
    if DEBUG:
        import cgitb
        cgitb.enable()  # This line enables CGI error reporting
    try:
        cgi_management()
    except Exception as e:
        if isinstance(e, SelfhostedDocsException):
            e.cgi_error()
        else:
            OriginalException(e).cgi_error()


settings = Settings()


def execute_args(args):
    if not getattr(args, 'which', None) or args.which == 'cgi_start':
        logging.basicConfig(level=logging.INFO)
        HOST, PORT = "localhost", 9997  # not really needed here
        server = Server((HOST, PORT), Handler)
        server.serve_forever()
    elif args.which == 'reload':
        reload(args.project_name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Reload project documentation.')
    parser.sub = parser.add_subparsers()
    parse_cgi_start = parser.sub.add_parser('cgi_start')
    parse_cgi_start.set_defaults(which='cgi_start')
    parse_reload = parser.sub.add_parser('reload')
    parse_reload.add_argument('project_name')
    parse_reload.set_defaults(which='reload')

    args = parser.parse_args()
    execute_args(args)
