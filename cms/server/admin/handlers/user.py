#!/usr/bin/env python3

# Contest Management System - http://cms-dev.github.io/
# Copyright © 2010-2013 Giovanni Mascellani <mascellani@poisson.phc.unipi.it>
# Copyright © 2010-2015 Stefano Maggiolo <s.maggiolo@gmail.com>
# Copyright © 2010-2012 Matteo Boscariol <boscarim@hotmail.com>
# Copyright © 2012-2018 Luca Wehrstedt <luca.wehrstedt@gmail.com>
# Copyright © 2014 Artem Iglikov <artem.iglikov@gmail.com>
# Copyright © 2014 Fabian Gundlach <320pointsguy@gmail.com>
# Copyright © 2016 Myungwoo Chun <mc.tamaki@gmail.com>
# Copyright © 2017 Valentin Rosca <rosca.valentin2012@gmail.com>
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

"""User-related handlers for AWS.

"""

from cms.db import Contest, Participation, Submission, Team, User
from cmscommon.datetime import make_datetime

from .base import BaseHandler, SimpleHandler, require_permission
from cmscontrib.loaders.simple_csv import CsvUserLoader
import cmscommon.crypto as crypto

import logging

logger = logging.getLogger(__name__)


class UserHandler(BaseHandler):
    @require_permission(BaseHandler.AUTHENTICATED)
    def get(self, user_id):
        user = self.safe_get_item(User, user_id)

        self.r_params = self.render_params()
        self.r_params["user"] = user
        self.r_params["participations"] = \
            self.sql_session.query(Participation)\
                .filter(Participation.user == user)\
                .all()
        self.r_params["unassigned_contests"] = \
            self.sql_session.query(Contest)\
                .filter(Contest.id.notin_(
                    self.sql_session.query(Participation.contest_id)
                        .filter(Participation.user == user)
                        .all()))\
                .all()
        self.render("user.html", **self.r_params)

    @require_permission(BaseHandler.PERMISSION_ALL)
    def post(self, user_id):
        fallback_page = self.url("user", user_id)

        user = self.safe_get_item(User, user_id)

        try:
            attrs = user.get_attrs()

            self.get_string(attrs, "first_name")
            self.get_string(attrs, "last_name")
            self.get_string(attrs, "username", empty=None)

            self.get_password(attrs, user.password, False)

            self.get_string(attrs, "email", empty=None)
            self.get_string_list(attrs, "preferred_languages")
            self.get_string(attrs, "timezone", empty=None)

            assert attrs.get("username") is not None, \
                "No username specified."

            # Update the user.
            user.set_attrs(attrs)

        except Exception as error:
            self.service.add_notification(
                make_datetime(), "Invalid field(s)", repr(error))
            self.redirect(fallback_page)
            return

        if self.try_commit():
            # Update the user on RWS.
            self.service.proxy_service.reinitialize()
        self.redirect(fallback_page)


class UserListHandler(SimpleHandler("users.html")):
    """Get returns the list of all users, post perform operations on
    a specific user (removing them from CMS).

    """

    REMOVE = "Remove"

    @require_permission(BaseHandler.AUTHENTICATED)
    def post(self):
        user_id = self.get_argument("user_id")
        operation = self.get_argument("operation")

        if operation == self.REMOVE:
            asking_page = self.url("users", user_id, "remove")
            # Open asking for remove page
            self.redirect(asking_page)
        else:
            self.service.add_notification(
                make_datetime(), "Invalid operation %s" % operation, "")
            self.redirect(self.url("contests"))


class RemoveUserHandler(BaseHandler):
    """Get returns a page asking for confirmation, delete actually removes
    the user from CMS.

    """

    @require_permission(BaseHandler.PERMISSION_ALL)
    def get(self, user_id):
        user = self.safe_get_item(User, user_id)
        submission_query = self.sql_session.query(Submission)\
            .join(Submission.participation)\
            .filter(Participation.user == user)
        participation_query = self.sql_session.query(Participation)\
            .filter(Participation.user == user)

        self.render_params_for_remove_confirmation(submission_query)
        self.r_params["user"] = user
        self.r_params["participation_count"] = participation_query.count()
        self.render("user_remove.html", **self.r_params)

    @require_permission(BaseHandler.PERMISSION_ALL)
    def delete(self, user_id):
        user = self.safe_get_item(User, user_id)

        self.sql_session.delete(user)
        if self.try_commit():
            self.service.proxy_service.reinitialize()

        # Maybe they'll want to do this again (for another user)
        self.write("../../users")


class TeamHandler(BaseHandler):
    """Manage a single team.

    If referred by GET, this handler will return a pre-filled HTML form.
    If referred by POST, this handler will sync the team data with the form's.
    """
    def get(self, team_id):
        team = self.safe_get_item(Team, team_id)

        self.r_params = self.render_params()
        self.r_params["team"] = team
        self.render("team.html", **self.r_params)

    def post(self, team_id):
        fallback_page = self.url("team", team_id)

        team = self.safe_get_item(Team, team_id)

        try:
            attrs = team.get_attrs()

            self.get_string(attrs, "code")
            self.get_string(attrs, "name")

            assert attrs.get("code") is not None, \
                "No team code specified."

            # Update the team.
            team.set_attrs(attrs)

        except Exception as error:
            self.service.add_notification(
                make_datetime(), "Invalid field(s)", repr(error))
            self.redirect(fallback_page)
            return

        if self.try_commit():
            # Update the team on RWS.
            self.service.proxy_service.reinitialize()
        self.redirect(fallback_page)


class AddTeamHandler(SimpleHandler("add_team.html", permission_all=True)):
    @require_permission(BaseHandler.PERMISSION_ALL)
    def post(self):
        fallback_page = self.url("teams", "add")

        try:
            attrs = dict()

            self.get_string(attrs, "code")
            self.get_string(attrs, "name")

            assert attrs.get("code") is not None, \
                "No team code specified."

            # Create the team.
            team = Team(**attrs)
            self.sql_session.add(team)

        except Exception as error:
            self.service.add_notification(
                make_datetime(), "Invalid field(s)", repr(error))
            self.redirect(fallback_page)
            return

        if self.try_commit():
            # Create the team on RWS.
            self.service.proxy_service.reinitialize()

        # In case other teams need to be added.
        self.redirect(fallback_page)


class AddUserHandler(SimpleHandler("add_user.html", permission_all=True)):
    @require_permission(BaseHandler.PERMISSION_ALL)
    def post(self):
        fallback_page = self.url("users", "add")

        try:
            attrs = dict()

            self.get_string(attrs, "first_name")
            self.get_string(attrs, "last_name")
            self.get_string(attrs, "username", empty=None)

            self.get_password(attrs, None, False)

            self.get_string(attrs, "email", empty=None)

            assert attrs.get("username") is not None, \
                "No username specified."

            self.get_string(attrs, "timezone", empty=None)

            self.get_string_list(attrs, "preferred_languages")

            # Create the user.
            user = User(**attrs)
            self.sql_session.add(user)

        except Exception as error:
            self.service.add_notification(
                make_datetime(), "Invalid field(s)", repr(error))
            self.redirect(fallback_page)
            return

        if self.try_commit():
            # Create the user on RWS.
            self.service.proxy_service.reinitialize()
            self.redirect(self.url("user", user.id))
        else:
            self.redirect(fallback_page)


class AddParticipationHandler(BaseHandler):
    @require_permission(BaseHandler.PERMISSION_ALL)
    def post(self, user_id):
        fallback_page = self.url("user", user_id)

        user = self.safe_get_item(User, user_id)

        try:
            contest_id = self.get_argument("contest_id")
            assert contest_id != "null", "Please select a valid contest"
        except Exception as error:
            self.service.add_notification(
                make_datetime(), "Invalid field(s)", repr(error))
            self.redirect(fallback_page)
            return

        self.contest = self.safe_get_item(Contest, contest_id)

        attrs = {}
        self.get_bool(attrs, "hidden")
        self.get_bool(attrs, "unrestricted")

        # Create the participation.
        participation = Participation(contest=self.contest,
                                      user=user,
                                      hidden=attrs["hidden"],
                                      unrestricted=attrs["unrestricted"])
        self.sql_session.add(participation)

        if self.try_commit():
            # Create the user on RWS.
            self.service.proxy_service.reinitialize()

        # Maybe they'll want to do this again (for another contest).
        self.redirect(fallback_page)


class EditParticipationHandler(BaseHandler):
    @require_permission(BaseHandler.PERMISSION_ALL)
    def post(self, user_id):
        fallback_page = self.url("user", user_id)

        user = self.safe_get_item(User, user_id)

        try:
            contest_id = self.get_argument("contest_id")
            operation = self.get_argument("operation")
            assert contest_id != "null", "Please select a valid contest"
            assert operation in (
                "Remove",
            ), "Please select a valid operation"
        except Exception as error:
            self.service.add_notification(
                make_datetime(), "Invalid field(s)", repr(error))
            self.redirect(fallback_page)
            return

        self.contest = self.safe_get_item(Contest, contest_id)

        if operation == "Remove":
            # Remove the participation.
            participation = self.sql_session.query(Participation)\
                .filter(Participation.user == user)\
                .filter(Participation.contest == self.contest)\
                .first()
            self.sql_session.delete(participation)

        if self.try_commit():
            # Create the user on RWS.
            self.service.proxy_service.reinitialize()

        # Maybe they'll want to do this again (for another contest).
        self.redirect(fallback_page)


class ImportUsersHandler(
        SimpleHandler("users_import.html", permission_all=True)):
    @require_permission(BaseHandler.PERMISSION_ALL)
    def post(self):
        fallback_page = self.url("users", "import")

        r_params = self.render_params()
        action = self.get_body_argument('action', 'upload')

        if action == 'upload':
            ignore_existing = self.get_body_argument('ignore_existing', False)
            generate_passwords = self.get_body_argument('generate_passwords',
                                                        False)
            ignored = 0
            try:
                user_csv = self.request.files["users_csv"][0]
                users = CsvUserLoader(None, None, user_csv['body']).get_users()
                processed_users = []
                for user in users:
                    if generate_passwords or callable(user.password):
                        user.password = None
                    db_user = self.sql_session.query(User).filter_by(
                        username=user.username).first()
                    if db_user:
                        if ignore_existing:
                            if db_user.password:
                                db_user.password = 'not_empty'
                            processed_users.append((False, db_user))
                            ignored += 1
                        else:
                            self.application.service.add_notification(
                                make_datetime(), 'Import failed',
                                'User "%s" already exists' % user.username)
                            self.redirect(fallback_page)
                            return
                    else:
                        processed_users.append((True, user))

                if ignored:
                    self.application.service.add_notification(
                        make_datetime(),
                        "User exists",
                        '%d users already exist, ignored' % ignored)
                r_params['users'] = processed_users
                self.render("users_import_preview.html", **r_params)
                return
            except Exception as error:
                self.application.service.add_notification(
                    make_datetime(), "Bad CSV file", repr(error))
                self.redirect(fallback_page)
                return
        elif action == 'save':
            usernames = self.get_body_arguments('username', False)
            first_names = self.get_body_arguments('first_name', False)
            last_names = self.get_body_arguments('last_name', False)
            passwords = self.get_body_arguments('password', False)
            emails = self.get_body_arguments('email', False)
            for i in range(len(usernames)):
                args = {
                    'username': usernames[i],
                    'first_name': first_names[i],
                    'last_name': last_names[i],
                    'email': emails[i],
                }
                if passwords[i]:
                    args['password'] = passwords[i]
                else:
                    args['password'] = crypto.generate_random_password()
                args['password'] = crypto.hash_password(args['password'], method='plaintext')
                user = User(**args)
                self.sql_session.add(user)
            if self.try_commit():
                # Create the user on RWS.
                self.application.service.proxy_service.reinitialize()
                self.redirect(self.url("users"))
                return
            else:
                self.redirect(fallback_page)
                return
        self.redirect(fallback_page)
