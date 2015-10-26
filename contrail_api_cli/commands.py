import inspect
import argparse

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
        self.current_path = current_path
        args = self.parser.parse_args(args=args)
        result = self.run(**args.__dict__)
        return (self.current_path, result)


class ExperimentalCommand(Command):

    def __call__(self, *args):
        print("This command is experimental. Use at your own risk.")
        return Command.__call__(self, *args)


class Ls(Command):
    description = "List resource objects"
    resource = Arg(nargs="?", help="Resource path", default="")

    def run(self, resource=''):
        # Find Path from fq_name
        if ":" in resource:
            target = APIClient().fqname_to_id(self.current_path, resource)
            if target is None:
                print("Can't find %s" % resource)
                return
        else:
            target = self.current_path / resource

        if target.is_collection or target.is_root:
            return utils.Collection(path=target, current_path=self.current_path)
        elif target.is_resource:
            return utils.Resource(path=target, current_path=self.current_path)


class Count(Command):
    description = "Count number of resources"
    resource = Arg(nargs="?", help="Resource path", default='')

    def run(self, resource=''):
        target = self.current_path / resource
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

    def run(self, resource='', recursive=False):
        target = self.current_path / resource
        if not target.is_resource:
            raise CommandError('"%s" is not a resource.' % target.relative_to(self.current_path))

        back_refs = [target]
        if recursive:
            back_refs = self._get_back_refs(target, [])
        if back_refs:
            print("About to delete:\n - %s" %
                  "\n - ".join([str(p.relative_to(self.current_path)) for p in back_refs]))
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

    def run(self, resource=''):
        self.current_path = self.current_path / resource


class Exit(Command):
    description = "Exit from cli"

    def run(self):
        raise EOFError


class Help(Command):

    def run(self):
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
