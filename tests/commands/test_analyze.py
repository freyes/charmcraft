# Copyright 2021 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# For further info, check https://github.com/canonical/charmcraft

import json
import logging
import zipfile
from argparse import Namespace, ArgumentParser
from unittest.mock import patch, ANY

import pytest

from charmcraft import linters
from charmcraft.cmdbase import CommandError
from charmcraft.commands.analyze import AnalyzeCommand, JSON_FORMAT
from charmcraft.utils import useful_filepath


def test_options_filepath_type(config):
    """The filepath parameter implies a set of validations."""
    cmd = AnalyzeCommand("group", config)
    parser = ArgumentParser()
    cmd.fill_parser(parser)
    (action,) = [action for action in parser._actions if action.dest == "filepath"]
    assert action.type is useful_filepath


def test_options_format_possible_values(config):
    """The format option implies a set of validations."""
    cmd = AnalyzeCommand("group", config)
    parser = ArgumentParser()
    cmd.fill_parser(parser)
    (action,) = [action for action in parser._actions if action.dest == "format"]
    assert action.choices == ["json"]


def test_expanded_charm(config, tmp_path, monkeypatch):
    """Check that the analyze runs on the temp directory with the extracted charm."""
    # prepare a fake charm file with some specific content just to check it was used properly
    charm_file = tmp_path / "foobar.charm"
    with zipfile.ZipFile(str(charm_file), "w") as zf:
        zf.writestr("fake_file", b"fake content")

    # this is to flag that the fake analyzer was called (otherwise the internal
    # verifications would be "lost")
    fake_analyze_called = False

    def fake_analyze(passed_config, passed_basedir, *, override_ignore_config):
        """Verify that the analyzer was called with the proper content.

        As we cannot check the directory itself (is temporal), we validate by content.
        """
        nonlocal fake_analyze_called

        fake_analyze_called = True
        assert passed_config is config
        assert (passed_basedir / "fake_file").read_text() == "fake content"
        assert override_ignore_config is False
        return []

    monkeypatch.setattr(linters, "analyze", fake_analyze)
    args = Namespace(filepath=charm_file, force=None, format=None)
    AnalyzeCommand("group", config).run(args)
    assert fake_analyze_called


def test_corrupt_charm(tmp_path, config):
    """There was a problem opening the indicated charm."""
    charm_file = tmp_path / "foobar.charm"
    charm_file.write_text("this is not a real zip content")

    args = Namespace(filepath=charm_file, force=None, format=None)
    with pytest.raises(CommandError) as cm:
        AnalyzeCommand("group", config).run(args)
    assert str(cm.value) == (
        "Cannot open the indicated charm file '{}': "
        "BadZipFile('File is not a zip file').".format(charm_file)
    )


def create_a_valid_zip(tmp_path):
    """Prepare a simple zip file."""
    zip_file = tmp_path / "foobar.charm"
    with zipfile.ZipFile(str(zip_file), "w") as zf:
        zf.writestr("fake_file", b"fake content")
    return zip_file


def test_integration_linters(tmp_path, caplog, config, monkeypatch):
    """Integration test with the real linters.analyze function (as other tests fake it)."""
    caplog.set_level(logging.DEBUG, logger="charmcraft")

    fake_charm = create_a_valid_zip(tmp_path)
    args = Namespace(filepath=fake_charm, force=None, format=None)
    AnalyzeCommand("group", config).run(args)

    expected_titles = ["Attributes:", "Lint Errors:"]
    logged = [rec.message for rec in caplog.records]
    assert all(x in logged for x in expected_titles)


@pytest.mark.parametrize("indicated_format", [None, JSON_FORMAT])
def test_complete_set_of_results(caplog, config, monkeypatch, tmp_path, indicated_format):
    """Show a complete basic case of results."""
    caplog.set_level(logging.DEBUG, logger="charmcraft")

    # fake results from the analyzer
    linting_results = [
        linters.CheckResult(
            name="check-lint-01",
            check_type=linters.CheckType.lint,
            url="url-01",
            text="text-01",
            result=linters.WARNINGS,
        ),
        linters.CheckResult(
            name="check-lint-02",
            check_type=linters.CheckType.lint,
            url="url-02",
            text="text-02",
            result=linters.OK,
        ),
        linters.CheckResult(
            name="check-lint-03",
            check_type=linters.CheckType.lint,
            url="url-03",
            text="text-03",
            result=linters.ERRORS,
        ),
        linters.CheckResult(
            name="check-attribute-04",
            check_type=linters.CheckType.attribute,
            url="url-04",
            text="text-04",
            result="check-result-04",
        ),
        linters.CheckResult(
            name="check-attribute-05",
            check_type=linters.CheckType.attribute,
            url="url-05",
            text="text-05",
            result=linters.IGNORED,
        ),
        linters.CheckResult(
            name="check-lint-06",
            check_type=linters.CheckType.lint,
            url="url-06",
            text="text-06",
            result=linters.IGNORED,
        ),
        linters.CheckResult(
            name="check-lint-07",
            check_type=linters.CheckType.lint,
            url="url-07",
            text="text-07",
            result=linters.FATAL,
        ),
    ]

    fake_charm = create_a_valid_zip(tmp_path)
    args = Namespace(filepath=fake_charm, force=None, format=indicated_format)
    monkeypatch.setattr(linters, "analyze", lambda *a, **k: linting_results)
    with patch.object(linters, "analyze") as mock_analyze:
        mock_analyze.return_value = linting_results
        AnalyzeCommand("group", config).run(args)
    mock_analyze.assert_called_with(config, ANY, override_ignore_config=False)

    if indicated_format is None:
        expected = [
            "Attributes:",
            "- check-attribute-04: check-result-04 (url-04)",
            "- check-attribute-05: ignored (url-05)",
            "Lint Ignored:",
            "- check-lint-06 (url-06)",
            "Lint Warnings:",
            "- check-lint-01: text-01 (url-01)",
            "Lint Errors:",
            "- check-lint-03: text-03 (url-03)",
            "Lint Fatal:",
            "- check-lint-07 (url-07)",
            "Lint OK:",
            "- check-lint-02: no issues found (url-02)",
        ]
        assert expected == [rec.message for rec in caplog.records]
    else:
        expected = [
            {
                "name": "check-lint-01",
                "type": "lint",
                "url": "url-01",
                "result": "warnings",
            },
            {
                "name": "check-lint-02",
                "type": "lint",
                "url": "url-02",
                "result": "ok",
            },
            {
                "name": "check-lint-03",
                "type": "lint",
                "url": "url-03",
                "result": "errors",
            },
            {
                "name": "check-attribute-04",
                "type": "attribute",
                "url": "url-04",
                "result": "check-result-04",
            },
            {
                "name": "check-attribute-05",
                "type": "attribute",
                "url": "url-05",
                "result": "ignored",
            },
            {
                "name": "check-lint-06",
                "type": "lint",
                "url": "url-06",
                "result": "ignored",
            },
            {
                "name": "check-lint-07",
                "type": "lint",
                "url": "url-07",
                "result": "fatal",
            },
        ]
        (logged_line,) = [rec.message for rec in caplog.records]
        assert expected == json.loads(logged_line)


def test_force_used_to_override_ignores(caplog, config, monkeypatch, tmp_path):
    """Show only attribute results (the rest may be ignored)."""
    fake_charm = create_a_valid_zip(tmp_path)
    args = Namespace(filepath=fake_charm, force=True, format=None)
    with patch.object(linters, "analyze") as mock_analyze:
        mock_analyze.return_value = []
        AnalyzeCommand("group", config).run(args)
    mock_analyze.assert_called_with(config, ANY, override_ignore_config=True)


def test_only_attributes(caplog, config, monkeypatch, tmp_path):
    """Show only attribute results (the rest may be ignored)."""
    caplog.set_level(logging.DEBUG, logger="charmcraft")

    # fake results from the analyzer
    linting_results = [
        linters.CheckResult(
            name="check-attribute",
            check_type=linters.CheckType.attribute,
            url="url",
            text="text",
            result="check-result",
        ),
    ]

    fake_charm = create_a_valid_zip(tmp_path)
    args = Namespace(filepath=fake_charm, force=None, format=None)
    monkeypatch.setattr(linters, "analyze", lambda *a, **k: linting_results)
    AnalyzeCommand("group", config).run(args)

    expected = [
        "Attributes:",
        "- check-attribute: check-result (url)",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_only_warnings(caplog, config, monkeypatch, tmp_path):
    """Show only warning results (the rest may be ignored)."""
    caplog.set_level(logging.DEBUG, logger="charmcraft")

    # fake results from the analyzer
    linting_results = [
        linters.CheckResult(
            name="check-lint",
            check_type=linters.CheckType.lint,
            url="url",
            text="text",
            result=linters.WARNINGS,
        ),
    ]

    fake_charm = create_a_valid_zip(tmp_path)
    args = Namespace(filepath=fake_charm, force=None, format=None)
    monkeypatch.setattr(linters, "analyze", lambda *a, **k: linting_results)
    AnalyzeCommand("group", config).run(args)

    expected = [
        "Lint Warnings:",
        "- check-lint: text (url)",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_only_errors(caplog, config, monkeypatch, tmp_path):
    """Show only error results (the rest may be ignored)."""
    caplog.set_level(logging.DEBUG, logger="charmcraft")

    # fake results from the analyzer
    linting_results = [
        linters.CheckResult(
            name="check-lint",
            check_type=linters.CheckType.lint,
            url="url",
            text="text",
            result=linters.ERRORS,
        ),
    ]

    fake_charm = create_a_valid_zip(tmp_path)
    args = Namespace(filepath=fake_charm, force=None, format=None)
    monkeypatch.setattr(linters, "analyze", lambda *a, **k: linting_results)
    AnalyzeCommand("group", config).run(args)

    expected = [
        "Lint Errors:",
        "- check-lint: text (url)",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_only_lint_ok(caplog, config, monkeypatch, tmp_path):
    """Show only lint results that are ok(the rest may be ignored)."""
    caplog.set_level(logging.DEBUG, logger="charmcraft")

    # fake results from the analyzer
    linting_results = [
        linters.CheckResult(
            name="check-lint",
            check_type=linters.CheckType.lint,
            url="url",
            text="text",
            result=linters.OK,
        ),
    ]

    fake_charm = create_a_valid_zip(tmp_path)
    args = Namespace(filepath=fake_charm, force=None, format=None)
    monkeypatch.setattr(linters, "analyze", lambda *a, **k: linting_results)
    AnalyzeCommand("group", config).run(args)

    expected = [
        "Lint OK:",
        "- check-lint: no issues found (url)",
    ]
    assert expected == [rec.message for rec in caplog.records]
