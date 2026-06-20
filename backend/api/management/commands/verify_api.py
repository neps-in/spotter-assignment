"""Run the live verification suite from the CLI.

    python manage.py verify_api          # one run, random cities
    python manage.py verify_api --runs 3 # three runs, fresh cities each time

Exits non-zero if any testcase fails, so it can gate CI.
"""
from django.core.management.base import BaseCommand

from api.verification import run_suite


class Command(BaseCommand):
    help = 'Run the 5-case live verification suite against /api/route/.'

    def add_arguments(self, parser):
        parser.add_argument('--runs', type=int, default=1,
                            help='Number of suite runs (each picks new random cities).')

    def handle(self, *args, **options):
        all_ok = True
        for run in range(1, options['runs'] + 1):
            report = run_suite()
            route = report['route_under_test']
            self.stdout.write(self.style.HTTP_INFO(
                f"\nRun {run}/{options['runs']}  [{report['run_id']}]  "
                f"{route['start']} -> {route['finish']}"))
            for test in report['tests']:
                mark = self.style.SUCCESS('PASS') if test['passed'] else self.style.ERROR('FAIL')
                self.stdout.write(f"  [{mark}] {test['id']}. {test['name']} - {test['details']}")
            s = report['summary']
            line = f"  => {s['passed']}/{s['total']} passed"
            self.stdout.write(self.style.SUCCESS(line) if s['all_passed']
                             else self.style.ERROR(line))
            all_ok = all_ok and s['all_passed']

        if not all_ok:
            raise SystemExit(1)
