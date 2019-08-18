#!/usr/bin/env python3

# Contest Management System - http://cms-dev.github.io/
# Copyright © 2010-2013 Giovanni Mascellani <mascellani@poisson.phc.unipi.it>
# Copyright © 2010-2018 Stefano Maggiolo <s.maggiolo@gmail.com>
# Copyright © 2010-2012 Matteo Boscariol <boscarim@hotmail.com>
# Copyright © 2012-2014 Luca Wehrstedt <luca.wehrstedt@gmail.com>
# Copyright © 2014 Artem Iglikov <artem.iglikov@gmail.com>
# Copyright © 2014 Fabian Gundlach <320pointsguy@gmail.com>
# Copyright © 2015 William Di Luigi <williamdiluigi@gmail.com>
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

"""Ranking-related handlers for AWS for a specific contest.

"""

import csv
import io
import locale

from sqlalchemy.orm import joinedload

from cms.db import Contest, SubmissionResult
from cms.grading.scoring import task_score, ScoredSubmission
from cms.grading.scoretypes import ScoreTypeGroup
from cms.db import Contest
from cms.grading.scoring import task_score
from .base import BaseHandler, require_permission


class RankingHandler(BaseHandler):
    """Shows the ranking for a contest.

    """
    @require_permission(BaseHandler.AUTHENTICATED)
    def get(self, contest_id, format="online"):
        # This validates the contest id.
        self.safe_get_item(Contest, contest_id)

        # This massive joined load gets all the information which we will need
        # to generating the rankings.
        self.contest = self.sql_session.query(Contest)\
            .filter(Contest.id == contest_id)\
            .options(joinedload('participations'))\
            .options(joinedload('participations.submissions'))\
            .options(joinedload('participations.submissions.token'))\
            .options(joinedload('participations.submissions.results'))\
            .first()

        # Preprocess participations: get data about teams, scores
        show_teams = False
        for p in self.contest.participations:
            show_teams = show_teams or p.team_id

            p.scores = []
            total_score = 0.0
            partial = False
            for task in self.contest.tasks:
                t_score, t_partial = task_score(p, task, rounded=True)
                p.scores.append((t_score, t_partial))
                total_score += t_score
                partial = partial or t_partial
            total_score = round(total_score, self.contest.score_precision)
            p.total_score = (total_score, partial)

        self.r_params = self.render_params()
        self.r_params["show_teams"] = show_teams
        if format == "txt":
            self.set_header("Content-Type", "text/plain")
            self.set_header("Content-Disposition",
                            "attachment; filename=\"ranking.txt\"")
            self.render("ranking.txt", **self.r_params)
        elif format == "csv":
            self.set_header("Content-Type", "text/csv")
            self.set_header("Content-Disposition",
                            "attachment; filename=\"ranking.csv\"")

            output = io.StringIO()  # untested
            writer = csv.writer(output)

            include_partial = True

            contest = self.r_params["contest"]

            row = ["Username", "User"]
            if show_teams:
                row.append("Team")
            for task in contest.tasks:
                row.append(task.name)
                if include_partial:
                    row.append("P")

            row.append("Global")
            if include_partial:
                row.append("P")

            writer.writerow(row)

            for p in sorted(contest.participations,
                            key=lambda p: p.total_score, reverse=True):
                if p.hidden:
                    continue

                row = [p.user.username,
                       "%s %s" % (p.user.first_name, p.user.last_name)]
                if show_teams:
                    row.append(p.team.name if p.team else "")
                assert len(contest.tasks) == len(p.scores)
                for t_score, t_partial in p.scores:  # Custom field, see above
                    row.append(t_score)
                    if include_partial:
                        row.append("*" if t_partial else "")

                total_score, partial = p.total_score  # Custom field, see above
                row.append(total_score)
                if include_partial:
                    row.append("*" if partial else "")

                writer.writerow(row)  # untested

            self.finish(output.getvalue())
        else:
            self.render("ranking.html", **self.r_params)


class DetailedResultsHandler(BaseHandler):
    """Show detailed results for printing.

    """
    @staticmethod
    def __get_result(text):
        # See EVALUATION_MESSAGES in cms/grading/steps/evaluation.py
        # TODO: use translation files when AWS supports them
        text, = text
        messages = {
            "Output is correct": "Pareizi",
            "Output is partially correct": "Daļēji pareizi",
            "Output isn't correct": "Nepareizi",
            "Evaluation didn't produce file %s": "Nav izvaddatu",
            "Execution timed out": "Laika limits",
            "Execution timed out (wall clock limit exceeded)": "Laika limits",
            "Execution killed (could be triggered by violating "
                "memory limits)": "Izpildes kļūda",
            "Execution failed because the return code was nonzero":
                "Izpildes kļūda"
         }
        if text in messages:
            return messages[text]
        return text

    @staticmethod
    def __format_score(score, max_score, precision):
        format_str = "%.{0}f/%.{0}f".format(precision)
        return locale.format_string(format_str, (score, max_score))

    @require_permission(BaseHandler.AUTHENTICATED)
    def get(self, contest_id):
        # This validates the contest id.
        self.safe_get_item(Contest, contest_id)

        # This massive joined load gets all the information which we will need
        # to generating the rankings.
        contest = self.sql_session.query(Contest) \
            .filter(Contest.id == contest_id) \
            .options(joinedload('participations')) \
            .options(joinedload('participations.submissions')) \
            .options(joinedload('participations.submissions.token')) \
            .options(joinedload('participations.submissions.results')) \
            .first()

        r_params = {
            'contest': contest,
            'format_score': DetailedResultsHandler.__format_score
        }
        partial_results = False
        results = []

        max_score = 0
        for task in contest.tasks:
            dataset = task.active_dataset
            scoretype = dataset.score_type_object
            max_score += scoretype.max_score

        for p in sorted(contest.participations,
                        key=lambda p: (locale.strxfrm(p.user.last_name),
                                       locale.strxfrm(p.user.first_name))):
            if p.hidden:
                continue

            result = {
                'participation': p,
                'max_score': max_score
            }
            total_score = 0
            task_results = []
            for task in contest.tasks:
                submission = ScoredSubmission()
                score, partial = task_score(p, task, rounded=True,
                                            submission=submission)
                if partial:
                    partial_results = True
                st = task.active_dataset.score_type_object
                if not isinstance(st, ScoreTypeGroup):
                    raise Exception("Unsupported score type for task {}"
                                    .format(task.name))

                task_max_score = st.max_score
                total_score += score

                test_results = []
                if submission.s:
                    sr = submission.s.get_result(task.active_dataset)
                    if sr:
                        status = sr.get_status()
                    else:
                        status = SubmissionResult.COMPILING

                    if status == SubmissionResult.SCORED:
                        test_results = sr.score_details
                        for group in test_results:
                            for testcase in group['testcases']:
                                testcase['text'] = DetailedResultsHandler\
                                        .__get_result(testcase['text'])
                else: # skip tasks with no submissions
                    assert score == 0.0
                    continue

                task_result = {
                    'task': task,
                    'score': score,
                    'max_score': task_max_score,
                    'status': status,
                    'test_results': test_results
                }

                task_results.append(task_result)
            result['total_score'] = total_score
            result['tasks'] = task_results

            results.append(result)

        r_params['results'] = results
        r_params['partial_results'] = partial_results

        self.set_header('Content-Type', 'text/html')
        self.set_header('Content-Disposition',
                        'attachment; filename="detailed_results.html"')
        self.render('detailed_results.html', **r_params)
