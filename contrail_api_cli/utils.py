import os.path
import json
from uuid import UUID
try:
    from UserDict import UserDict
except ImportError:
    from collections import UserDict
try:
    from Queue import Queue
except ImportError:
    from queue import Queue
from threading import Thread
from pathlib import PurePosixPath

from pygments import highlight
from pygments.lexers import JsonLexer
from pygments.formatters import Terminal256Formatter

from prompt_toolkit import prompt
from prompt_toolkit.completion import Completer, Completion


COMPLETION_QUEUE = Queue()


class PathEncoder(json.JSONEncoder):

    def default(self, obj):
        if isinstance(obj, Path):
            return str(obj)
        return super(self, PathEncoder).default(obj)


class FullPathEncoder(json.JSONEncoder):

    def default(self, obj):
        if isinstance(obj, Path):
            return obj.url
        return super(self, FullPathEncoder).default(obj)


class ResourceCompletionFiller(Thread):

    def __init__(self, completer):
        super(ResourceCompletionFiller, self).__init__()
        self.completer = completer
        self.daemon = True

    def run(self):
        while True:
            res = COMPLETION_QUEUE.get()
            for r in self.completer.resources[:]:
                if res.path == r.path:
                    self.completer.resources.remove(r)
                    break
            self.completer.resources.append(res)
            COMPLETION_QUEUE.task_done()


class ResourceCompleter(Completer):
    """
    Simple autocompletion on a list of paths.
    """
    def __init__(self):
        self.resources = []

    def get_completions(self, document, complete_event):
        path_before_cursor = document.get_word_before_cursor(WORD=True).lower()

        def resource_matches(res):
            fields = [str(res.rel_path), res.fq_name]
            return any([path_before_cursor in f for f in fields])

        from contrail_api_cli.prompt import CURRENT_PATH

        def resource_sort(resource):
            # Make the relative paths of the resource appear first in
            # the list
            if resource.path.resource_name == CURRENT_PATH.resource_name:
                return "_"
            return resource.path.resource_name

        for res in sorted(self.resources, key=resource_sort):
            if res.rel_path in ('.', '/', ''):
                continue
            if resource_matches(res):
                yield Completion(str(res.rel_path),
                                 -len(path_before_cursor),
                                 display_meta=res.fq_name)


class Collection(object, UserDict):

    def __init__(self, retrieve=True, current_path=None, **kwargs):
        assert isinstance(kwargs.get('path'), Path)
        UserDict.__init__(self, items=[], **kwargs)
        self.fq_name = ""
        self.current_path = current_path or Path("/")
        if retrieve:
            self._get()
        COMPLETION_QUEUE.put(self)

    @property
    def path(self):
        return self.data.get("path")

    @property
    def rel_path(self):
        from contrail_api_cli.prompt import CURRENT_PATH
        return self.path.relative_to(CURRENT_PATH)

    @property
    def items(self):
        return self.data.get("items", [])

    @items.setter
    def items(self, values):
        self.data["items"] = values

    def _get(self):
        from contrail_api_cli.client import APIClient
        data = APIClient().get(self.path)

        if self.path.is_root:
            self.items = [Collection(retrieve=False,
                                     current_path=self.current_path,
                                     **l["link"])
                          for l in data['links']
                          if l["link"]["rel"] == "resource-base"]
        elif self.path.is_collection:
            self.items = [Resource(retrieve=False,
                                   current_path=self.current_path,
                                   **res)
                          for res_name, res_list in data.items()
                          for res in res_list]

    def __str__(self):
        return "\n".join([str(item.path.relative_to(self.current_path))
                          for item in self.items])


class Resource(object, UserDict):

    def __init__(self, retrieve=True, current_path=None, **kwargs):
        assert isinstance(kwargs.get('path'), Path)
        UserDict.__init__(self, **kwargs)
        self.current_path = current_path or Path("/")
        if retrieve:
            self._get()
        COMPLETION_QUEUE.put(self)

    @property
    def path(self):
        return self.data.get("path")

    @property
    def rel_path(self):
        from contrail_api_cli.prompt import CURRENT_PATH
        return self.path.relative_to(CURRENT_PATH)

    @property
    def fq_name(self):
        return ":".join(self.data.get("fq_name", self.data.get("to", [])))

    def _get(self):
        from contrail_api_cli.client import APIClient
        self.data.update(APIClient().get(self.path)[self.path.resource_name])
        # Find other linked resources
        self.data = self._walk_resource(self.data)

    def _walk_resource(self, data):
        if 'path' in data:
            Resource(retrieve=False, current_path=self.current_path, **data)
        for attr, value in list(data.items()):
            if attr.endswith('refs'):
                for idx, r in enumerate(data[attr]):
                    data[attr][idx] = self._walk_resource(data[attr][idx])
            if type(data[attr]) is dict:
                data[attr] = self._walk_resource(data[attr])
        return data

    def __str__(self):
        json_data = json.dumps(self.data, sort_keys=True, indent=2,
                               cls=PathEncoder,
                               separators=(',', ': '))
        return highlight(json_data,
                         JsonLexer(indent=2),
                         Terminal256Formatter(bg="dark"))


class Path(PurePosixPath):

    @classmethod
    def _from_parsed_parts(cls, drv, root, parts, init=True):
        if parts:
            parts = [root] + os.path.relpath(os.path.join(*parts), start=root).split(os.path.sep)
            parts = [p for p in parts if p not in (".", "")]
        return super(cls, Path)._from_parsed_parts(drv, root, parts, init)

    def __init__(self, *args):
        self.meta = {}

    @property
    def resource_name(self):
        try:
            return self.parts[1]
        except IndexError:
            pass

    @property
    def is_root(self):
        return len(self.parts) == 1 and self.root == "/"

    @property
    def is_resource(self):
        try:
            UUID(self.name, version=4)
        except (ValueError, IndexError):
            return False
        return True

    @property
    def is_collection(self):
        return not self.is_resource and self.resource_name

    def relative_to(self, path):
        try:
            return PurePosixPath.relative_to(self, path)
        except ValueError:
            return self


class classproperty(object):

    def __init__(self, f):
        self.f = f

    def __get__(self, instance, klass):
        if instance:
            try:
                return self.f(instance)
            except AttributeError:
                pass
        return self.f(klass)


def continue_prompt():
    answer = False
    while answer not in ('Yes', 'No'):
        answer = prompt(u"'Yes' or 'No' to continue: ")
        if answer == "Yes":
            answer = True
            break
        if answer == "No":
            answer = False
            break
    return answer


def to_json(resource_dict):
    return json.dumps(resource_dict,
                      sort_keys=True,
                      indent=2,
                      separators=(',', ': '),
                      cls=FullPathEncoder)


def from_json(resource_json):
    return json.loads(resource_json, object_hook=decode_paths)


def decode_paths(obj):
    for attr, value in obj.items():
        if attr in ('href', 'parent_href'):
            obj["path"] = href_to_path(value)
    return obj


def href_to_path(href):
    from contrail_api_cli.client import APIClient
    return Path(href[len(APIClient.base_url):])
