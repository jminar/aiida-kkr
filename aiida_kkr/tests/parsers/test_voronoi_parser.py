#!/usr/bin/env python

from __future__ import absolute_import
from builtins import object
import pytest
from aiida.manage.tests.pytest_fixtures import clear_database, clear_database_after_test, aiida_profile

# tests
def test_parse_voronoi_calc(aiida_profile):
    """
    ...
    """
    from aiida.orm import load_node
    from aiida_kkr.parsers.voro import VoronoiParser
    from aiida.tools.importexport import import_data
    import_data('files/db_dump_vorocalc.tar.gz')
    voro_calc = load_node('559b9d9b-3525-402e-9b24-ecd8b801853c')
    parser = VoronoiParser(voro_calc)
    out = parser.parse(debug=False)
    assert out is None
    out_dict = parser.outputs.output_parameters.get_dict()
    assert out_dict['parser_errors'] == []