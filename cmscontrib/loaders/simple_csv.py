#!/usr/bin/env python2
# -*- coding: utf-8 -*-

# Programming contest management system
# Copyright © 2016 Karlis Senko <karlis3p70l1ij@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import logging
import os
from backports import csv  # Use native csv reader in python3
import io

from cms.db import User

from .base_loader import UserLoader

logger = logging.getLogger(__name__)


class CsvUserLoader(UserLoader):
    """Load users from CSV file.

    Flexible CSV user loader.
    """

    def get_task_loader(self, taskname):
        raise Exception("get_task_loader is irrelevant for user loader")

    short_name = 'csv_user'
    description = 'Simple csv user lodaer'

    USER_FILE = "contestants.csv"

    def __init__(self, path, file_cacher, input_data=None):
        super(UserLoader, self).__init__(path, file_cacher)

        self.input_data = input_data
        self.real_path = None
        self.user = None
        if self.path:
            self.set_input_file_name()

    @staticmethod
    def detect(path):
        """See docstring in class Loader."""
        dir_name = os.path.dirname(path)
        return os.path.exists(
            os.path.join(dir_name, CsvUserLoader.USER_FILE)) or \
            os.path.basename(path) == CsvUserLoader.USER_FILE or \
            os.path.basename(dir_name) == CsvUserLoader.USER_FILE

    def user_has_changed(self):
        """See docstring in class Loader."""
        return True

    def set_input_file_name(self):
        if os.path.basename(self.path) == CsvUserLoader.USER_FILE:
            self.real_path = self.path
        elif os.path.exists(os.path.join(self.path, CsvUserLoader.USER_FILE)):
            self.real_path = os.path.join(self.path, CsvUserLoader.USER_FILE)
        else:
            dir_name, self.user = os.path.split(self.path)
            if os.path.basename(dir_name) == CsvUserLoader.USER_FILE:
                self.real_path = os.path.basename(dir_name)
            else:
                self.real_path = os.path.join(dir_name, CsvUserLoader.USER_FILE)

    def read_users(self):
        with io.StringIO(self.input_data.decode('utf-8')) if self.input_data \
          else io.open(self.real_path, 'r', encoding='utf-8') as input_file:
            return list(csv.DictReader(input_file))

    def get_users(self):
        users = self.read_users()
        result = []
        for user in users:
            args = {'username': user['username'],
                    'first_name': user.get('name', user['username']),
                    'last_name': user.get('last_name', ''),
                    'email': user.get('email', None)}
            password = user.get('password')
            if password:
                args['password'] = password

            user_obj = User(**args)

            result.append(user_obj)
        return result

    def get_user(self):
        users = self.get_users()
        users = filter(lambda user: user.username == self.user, users)
        if len(users) != 1:
            logger.critical("Incorrect user count %d", len(users))
            return None
        return users[0]
