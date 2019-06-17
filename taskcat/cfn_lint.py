import textwrap
import cfnlint.core
import re
import logging
from taskcat.config import Config

log = logging.getLogger(__name__)


class Lint(object):

    _code_regex = re.compile("^([WER][0-9]*:)")

    def __init__(self, config: Config, strict: bool = False):
        """
        Lints templates using cfn_python_lint. Uses config to define regions and templates to test. Recurses into
        child templates, excluding submodules.

        :param config: path to tascat ci config file
        """
        self._config: Config = config
        self._rules = cfnlint.core.get_rules([], [], [])
        self.lints = self._lint()
        self.strict: bool = strict

    def _filter_unsupported_regions(self, regions):
        lint_regions = set(cfnlint.core.REGIONS)
        if set(regions).issubset(lint_regions):
            return regions
        supported = set(regions).intersection(lint_regions)
        unsupported = set(regions).difference(lint_regions)
        log.error("The following regions are not supported by cfn-python-lint and will not be linted %s" % unsupported)
        return list(supported)

    def _lint(self):
        lints = {}

        for _, test in self._config.tests.items():
            lints[test.name] = {}
            lints[test.name]['regions'] = self._filter_unsupported_regions(test.regions)
            lints[test]['template_file'] = test.template_file
            lints[test]['results'] = {}

            lint_errors = set()
            templates = {t for t in test.template.descendents}
            templates.union(set(test.template))

            for t in templates:
                try:
                    lints[test]['results'][t] = cfnlint.core.run_checks(
                        t.template_path, t.template, self._rules,
                        lints[test]['regions']
                    )
                except cfnlint.core.CfnLintExitException as e:
                    lint_errors.add(str(e))
            for e in lint_errors:
                log.error(e)
        return lints, lint_errors

    def output_results(self):
        """
        Prints lint results to terminal using taskcat console formatting

        :return:
        """
        for test in self.lints.keys():
            for t in self.lints[test]['results'].keys():
                if len(self.lints[test]['results'][t]) == 0:
                    log.info("Lint passed for test %s on template %s:" % (test, t))
                else:
                    msg = "Lint detected issues for test %s on template %s:" % (test, t)
                    if self._is_error(self.lints[test]['results'][t]):
                        log.error(msg)
                    else:
                        log.warning(msg)
                for r in self.lints[test]['results'][t]:
                    self._format_message(r, test, t)

    @property
    def passed(self):
        for test in self.lints.keys():
            for t in self.lints[test]['results'].keys():
                if len(self.lints[test]['results'][t]) != 0:
                    if self._is_error(self.lints[test]['results'][t]) or self.strict:
                        return False
        return True

    @staticmethod
    def _is_error(messages):
        for m in messages:
            sev = m.__str__().lstrip('[')[0]
            if sev == 'E':
                return True
        return False

    def _format_message(self, message, test, t):
        message = message.__str__().lstrip('[')
        sev = message[0]
        code = Lint._code_regex.findall(message)[0][:-1]
        path = message.split(" ")[-1]
        line_no = ""
        if len(path.split(":")) == 2:
            line_no = path.split(":")[1]
        prefix = "    line " + line_no + " [" + code + "] ["
        indent = "\n" + " " * (2 + len(prefix))
        message = indent.join(textwrap.wrap(" ".join(message.split(" ")[1:-2]), 141-(len(indent) + 11)))
        message = prefix + message
        if sev == 'E':
            log.error(message)
        elif sev == 'W':
            if 'E' + message[1:] not in [r.__str__().lstrip('[') for r in self.lints[test]['results'][t]]:
                log.warning(message)
        else:
            log.error("linter produced unkown output: " + message)
