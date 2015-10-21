import inspect
import argparse
import json
import os
import subprocess
import tempfile

import json_delta

from pygments import highlight, lexers
from pygments.formatters import Terminal256Formatter

from contrail_api_cli import utils
from contrail_api_cli.client import APIClient, APIError


class CommandError(Exception):
    pass


class ArgumentParser(argparse.ArgumentParser):

    def exit(self, status=0, message=None):
        print(message)
        raise CommandError()


class Arg:

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class Command:
    description = ""

    def __init__(self, *args):
        self.parser = ArgumentParser(prog=self.__class__.__name__.lower(),
                                     description=self.description)
        for attr, value in inspect.getmembers(self.__class__):
            if isinstance(value, Arg):
                # Handle case for options
                # attr can't be something like '-r'
                if len(value.args) > 0:
                    attr = value.args[0]
                    value.args = value.args[1:]
                self.parser.add_argument(attr, *value.args, **value.kwargs)

    def __call__(self, current_path, *args):
        args = self.parser.parse_args(args=args)
        return self.run(current_path, **args.__dict__)


class ExperimentalCommand(Command):

    def __call__(self, *args):
        print("This command is experimental. Use at your own risk.")
        return Command.__call__(self, *args)


class Ls(Command):
    description = "List resource objects"
    resource = Arg(nargs="?", help="Resource path", default="")

    def walk_resource(self, data, current_path):
        data = self.transform_resource(data, current_path)
        for attr, value in list(data.items()):
            if attr.endswith('refs'):
                for idx, r in enumerate(data[attr]):
                    data[attr][idx] = self.walk_resource(data[attr][idx], current_path)
            if type(data[attr]) is dict:
                data[attr] = self.walk_resource(data[attr], current_path)
        return data

    def transform_resource(self, data, current_path):
        for attr, value in list(data.items()):
            if value is None:
                del data[attr]
            if attr in ("to", "fq_name"):
                data[attr] = ":".join(value)
            if attr in ("href", "parent_href"):
                data[attr] = value.relative_to(current_path)
                utils.COMPLETION_QUEUE.put(value)
        return data

    def colorize(self, data):
        json_data = json.dumps(data, sort_keys=True, indent=2,
                               cls=utils.PathEncoder,
                               separators=(',', ': '))
        return highlight(json_data,
                         lexers.JsonLexer(indent=2),
                         Terminal256Formatter(bg="dark"))

    def run(self, current_path, resource=''):
        # Find Path from fq_name
        if ":" in resource:
            target = APIClient().fqname_to_id(current_path, resource)
            if target is None:
                print("Can't find %s" % resource)
                return
        else:
            target = current_path / resource
        data = APIClient().list(target)
        if target.is_resource:
            data = self.walk_resource(data, current_path)
            return self.colorize(data)
        else:
            return data


class Count(Command):
    description = "Count number of resources"
    resource = Arg(nargs="?", help="Resource path", default='')

    def run(self, current_path, resource=''):
        target = current_path / resource
        if target.is_collection:
            data = APIClient().get(target, count=True)
            return data[target.resource_name + "s"]["count"]


class Rm(ExperimentalCommand):
    description = "Delete a resource"
    resource = Arg(nargs="?", help="Resource path", default='')
    recursive = Arg("-r", "--recursive", dest="recursive",
                    action="store_true", default=False,
                    help="Recursive delete of back_refs resources")

    def _get_back_refs(self, path, back_refs):
        resource = APIClient().get(path)[path.resource_name]
        if resource["href"] in back_refs:
            back_refs.remove(resource["href"])
        back_refs.append(resource["href"])
        for attr, values in resource.items():
            if not attr.endswith("back_refs"):
                continue
            for back_ref in values:
                back_refs = self._get_back_refs(back_ref["href"],
                                                back_refs)
        return back_refs

    def run(self, current_path, resource='', recursive=False):
        target = current_path / resource
        if not target.is_resource:
            raise CommandError('"%s" is not a resource.' % target.relative_to(current_path))

        back_refs = [target]
        if recursive:
            back_refs = self._get_back_refs(target, [])
        if back_refs:
            print("About to delete:\n - %s" %
                  "\n - ".join([str(p.relative_to(current_path)) for p in back_refs]))
            if utils.continue_prompt():
                for ref in reversed(back_refs):
                    print("Deleting %s" % str(ref))
                    try:
                        APIClient().delete(ref)
                    except APIError as e:
                        raise CommandError("Failed to delete all resources: %s\n \
                                            Try to delete the resource recursively with -r."
                                           % str(e))


class Cd(Command):
    description = "Change resource context"
    resource = Arg(nargs="?", help="Resource path", default='')

    def run(self, current_path, resource=''):
        return current_path / resource


class Exit(Command):
    description = "Exit from cli"

    def run(self, current_path):
        raise EOFError


class Edit(ExperimentalCommand):
    description = "Edit resource"
    resource = Arg(nargs="?", help="Resource path")

    def _calculate_minimal_diff(self, data, changes):
        diff = {
            self.resource_name: {}
        }
        changed_keys = [change[0][0] for change in changes]
        for key, values in data.items():
            if key in changed_keys:
                diff[self.resource_name][key] = values
        return diff

    def run(self, path, resource=None):
        target = utils.Path(str(path), resource)
        editor = os.environ.get('EDITOR', 'vim')
        self.resource_name = target.resource_name

        old_data = APIClient().get(target)[self.resource_name]
        old_data_json = utils.to_json(old_data)
        with tempfile.NamedTemporaryFile(suffix='tmp.json') as tmp:
            tmp.write(bytes(old_data_json, 'utf-8'))
            tmp.flush()
            subprocess.call([editor, tmp.name])
            tmp.seek(0)
            new_data_json = tmp.read().decode('utf-8')
            new_data = utils.from_json(new_data_json)
            if old_data != new_data:
                changes = json_delta.load_and_diff(old_data_json, new_data_json,
                                                   verbose=False)
                print("About to commit:\n")
                json_diff = "\n".join(json_delta.load_and_udiff(old_data_json,
                                                                new_data_json,
                                                                stanzas=changes))
                print(highlight(json_diff,
                                lexers.DiffLexer(),
                                Terminal256Formatter(bg="dark")))

                if utils.continue_prompt():
                    diff = self._calculate_minimal_diff(new_data, changes)
                    APIClient().put(target, data=diff)


class Help(Command):

    def run(self, current_path):
        commands = {}
        for name, obj in globals().items():
            if isinstance(obj, Command):
                if name != "help":
                    commands[obj] = name
        return "Available commands: %s" % " ".join(commands.values())


ls = ll = Ls()
cd = Cd()
help = Help()
count = Count()
rm = Rm()
exit = Exit()
edit = vim = emacs = Edit()
