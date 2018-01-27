#!/usr/bin/env python
import argparse
import logging
import subprocess
import toml

import os
from http import HTTPStatus

import sys
from traceback import print_exc

DEBUG = '--debug' in sys.argv

logger = logging.getLogger('selfhosted-docs')
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

    @property
    def key(self):
        return self._data['settings']['key']


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
        check_execution_success(['git', 'pull'], repo_directory)
    if not os.path.lexists(venv_directory):
        check_execution_success(['virtualenv', '.venv'], repo_directory)
    execute_venv(['pip', 'install', '-r', 'py3-requirements.txt'], repo_directory, venv_directory)
    execute_venv(['pip', 'install', '-r', 'requirements-dev.txt'], repo_directory, venv_directory)
    execute_venv(['make', 'html'], docs_directory, venv_directory)


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
    if key != settings.key:
        raise InvalidKeyException()
    os.system('nohup {}/reload.py reload \'{}\'&'.format(hooks_dir, repo_name))


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
        cgi_start()
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
