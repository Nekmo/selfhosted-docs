#!/usr/bin/env python
import logging
import subprocess
import toml

import os
from http import HTTPStatus

import sys
from traceback import print_exc

DEBUG = '--debug' in sys.argv
DEBUG = True

logger = logging.getLogger('amazon-dash')
hooks_dir = os.path.dirname(os.path.abspath(__file__))
projects_dir = os.path.dirname(hooks_dir)


def print_status_code(status: HTTPStatus):
    print('Status: {} {}'.format(status.value, status.name.replace('_', ' ').title()))


class Settings(object):
    def __init__(self, path=os.path.join(projects_dir, 'config.toml')):
        self._data = toml.load(open(path))

    def get_project(self, name):
        for project in self._data['projects']:
            if project['name'] == name:
                return project


class SelfhostedDocsException(Exception):
    status = HTTPStatus.INTERNAL_SERVER_ERROR
    message = ''

    def __init__(self, status: HTTPStatus=None, message: str=None):
        self.status = status or self.status
        self.message = message or self.message

    def cgi_error(self):
        print_status_code(self.status)
        print()
        print('({}) {}: {}'.format(self.status.value, self.__class__.__name__, self.message or 'Not message supplied'))


class OriginalException(SelfhostedDocsException):
    def __init__(self, exception: Exception, status: HTTPStatus=None):
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


def check_execution_success(cmd, cwd):
    p = subprocess.Popen(cmd, cwd=cwd, stderr=subprocess.PIPE)
    stdout, stderr = p.communicate()
    if p.returncode:
        logger.error('%i return code on "%s" command. Stderr: %s', p.returncode, ' '.join(cmd), stderr)


def reload(project_name: str):
    repo_directory = os.path.join(projects_dir, project_name)
    if not os.path.exists(repo_directory):
        check_execution_success(['git', 'clone', settings.get_project(project_name)['url']], projects_dir)


def cgi_management():
    import cgi
    print("Content-Type: text/html")
    arguments = cgi.FieldStorage()
    repo_name = arguments.getfirst('repo_name')
    key = arguments.getfirst('key')
    if not repo_name:
        raise MissingParameterException('repo_name')
    if not key:
        raise MissingParameterException('key')
    reload(repo_name)


settings = Settings()
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
