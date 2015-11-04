import sys
import pprint
import argparse

from prompt_toolkit import prompt
from prompt_toolkit.history import InMemoryHistory

from pygments.token import Token

from keystoneclient import session, auth

from contrail_api_cli.client import APIClient, APIError
from contrail_api_cli.style import PromptStyle
from contrail_api_cli import utils, commands

CURRENT_PATH = utils.Path('/')

history = InMemoryHistory()
completer = utils.PathCompleter(match_middle=True)
utils.PathCompletionFiller(completer).start()


class JustContinueException(Exception):
    pass


def get_prompt_tokens(cli):
    return [
        (Token.Username, APIClient.user),
        (Token.At, '@' if APIClient.user else ''),
        (Token.Host, APIClient.HOST),
        (Token.Colon, ':'),
        (Token.Path, str(CURRENT_PATH)),
        (Token.Pound, '> ')
    ]


def get_command_result(args):
    global CURRENT_PATH
    try:
        cmd = getattr(commands, args[0])
        args = args[1:]
    except AttributeError:
        print("Command not found. Type help for all commands.")
        raise JustContinueException()
    except IndexError:
        raise JustContinueException()
    try:
        CURRENT_PATH, result = cmd(CURRENT_PATH, *args)
    except commands.CommandError as e:
        print(e)
        raise JustContinueException()
    except APIError as e:
        print(e)
        raise JustContinueException()
    if result is None:
        raise JustContinueException()
    return result


def output_command_result(result):
    global CURRENT_PATH
    if type(result) == list:
        output_paths = []
        for p in result:
            output_paths.append(str(p.relative_to(CURRENT_PATH)))
            utils.COMPLETION_QUEUE.put(p)
        print("\n".join(output_paths))
    elif type(result) == dict:
        print(pprint.pformat(result, indent=2))
    else:
        print(result)


def main():
    argv = sys.argv[1:]

    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='localhost:8082',
                        help="host:port to connect to (default='%(default)s')")
    parser.add_argument('--ssl', action="store_true", default=False,
                        help="connect with SSL (default=%(default)s)")
    parser.add_argument('cmd', nargs="*")
    session.Session.register_cli_options(parser)
    # Default auth plugin will be http unless OS_AUTH_PLUGIN envvar is set
    auth.register_argparse_arguments(parser, argv, default="http")
    options = parser.parse_args()

    if options.ssl:
        APIClient.PROTOCOL = 'https'
    if options.host:
        APIClient.HOST = options.host

    auth_plugin = auth.load_from_argparse_arguments(options)
    APIClient.SESSION = session.Session.load_from_cli_options(options, auth=auth_plugin)

    if options.cmd:
        try:
            output_command_result(get_command_result(options.cmd))
        except JustContinueException:
            pass
        return

    for p in APIClient().list(CURRENT_PATH):
        utils.COMPLETION_QUEUE.put(p)

    while True:
        try:
            action = prompt(get_prompt_tokens=get_prompt_tokens,
                            history=history,
                            completer=completer,
                            style=PromptStyle)
        except (EOFError, KeyboardInterrupt):
            break
        try:
            result = get_command_result(action.split())
        except KeyboardInterrupt:
            continue
        except EOFError:
            break
        except JustContinueException:
            continue
        else:
            output_command_result(result)

if __name__ == "__main__":
    main()
