#!/usr/bin/env python3
"""Exercise favourites migration without touching a Kodi profile."""

import importlib.util
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
MODULE = (ROOT / 'wizard/source/plugin.program.kodipovilwizard/resources'
          / 'libs/build_favourites_migration.py')
spec = importlib.util.spec_from_file_location('build_favourites_migration', MODULE)
merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge)


def names(text):
    return [item.get('name') for item in ET.fromstring(text)]


class FavouritesMigrationTests(unittest.TestCase):
    OLD = ('<favourites><favourite name="Build" thumb="old.png">Open(old)</favourite>'
           '<favourite name="Removed" thumb="old.png">Open(removed)</favourite>'
           '<favourite name="Edited" thumb="old.png">Open(edited)</favourite>'
           '<favourite name="Legacy" thumb="old.png">Open(legacy)</favourite>'
           '</favourites>')
    NEW = ('<favourites><favourite name="Build" thumb="new.png">Open(new)</favourite>'
           '<favourite name="Removed" thumb="new.png">Open(removed-new)</favourite>'
           '<favourite name="Edited" thumb="new.png">Open(edited-new)</favourite>'
           '<favourite name="Added" thumb="new.png">Open(added)</favourite>'
           '</favourites>')
    USER = ('<favourites><favourite name="Custom" thumb="mine.png">Open(mine)</favourite>'
            '<favourite name="Edited" thumb="mine.png">Open(my-edit)</favourite>'
            '<favourite name="Build" thumb="old.png">Open(old)</favourite>'
            '<favourite name="Legacy" thumb="old.png">Open(legacy)</favourite>'
            '</favourites>')

    def test_preserves_user_changes_deletion_order_and_old_only_item(self):
        output, counts = merge.merge_favourites_xml(self.OLD, self.USER, self.NEW)
        self.assertEqual(names(output), ['Custom', 'Edited', 'Build', 'Legacy', 'Added'])
        items = {item.get('name'): item for item in ET.fromstring(output)}
        self.assertEqual(items['Build'].text, 'Open(new)')
        self.assertEqual(items['Edited'].text, 'Open(my-edit)')
        self.assertEqual(items['Custom'].get('thumb'), 'mine.png')
        self.assertEqual(items['Legacy'].text, 'Open(legacy)')
        self.assertNotIn('Removed', items)
        self.assertEqual(counts['updated'], 1)
        self.assertEqual(counts['added'], 1)
        self.assertEqual(counts['user_deleted'], 1)
        self.assertEqual(counts['old_only_retained'], 1)

    def test_reapplying_does_not_change_output(self):
        output, _ = merge.merge_favourites_xml(self.OLD, self.USER, self.NEW)
        again, counts = merge.merge_favourites_xml(self.OLD, output, self.NEW)
        self.assertEqual(again, output)
        self.assertEqual(counts['updated'], 0)
        self.assertEqual(counts['added'], 0)

    def test_no_change_preserves_original_xml_bytes(self):
        output, _ = merge.merge_favourites_xml(self.OLD, self.OLD, self.OLD)
        self.assertEqual(output, self.OLD)

    def test_ambiguous_or_malformed_inputs_fail_closed(self):
        bad = ('<favourites><favourite name="Build">A</favourite>'
               '<favourite name="Build">B</favourite></favourites>')
        for old, installed, new in ((bad, self.USER, self.NEW),
                                    (self.OLD, bad, self.NEW),
                                    (self.OLD, self.USER, bad),
                                    (self.OLD, '<favourites>', self.NEW)):
            with self.assertRaises(ValueError):
                merge.merge_favourites_xml(old, installed, new)


if __name__ == '__main__':
    unittest.main()
