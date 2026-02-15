
from django.test import TestCase
from django.template import Context, Template

class FileUtilsTest(TestCase):
    def test_basename_filter(self):
        t = Template("{% load file_utils %}{{ path|basename }}")
        c = Context({"path": "folder/subfolder/file.txt"})
        rendered = t.render(c)
        self.assertEqual(rendered, "file.txt")

    def test_basename_filter_empty(self):
        t = Template("{% load file_utils %}{{ path|basename }}")
        c = Context({"path": ""})
        rendered = t.render(c)
        self.assertEqual(rendered, "")
