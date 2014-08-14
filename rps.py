# pylint: disable=missing-docstring
from collections import OrderedDict, defaultdict
import argparse
import select
import socket
import string
import sys


class Style(object):
    RESET = 0
    BOLD = 1
    UNDERSCORE = 4
    BLINK = 5
    INVERT = 7
    CONCEAL = 8

    FG_BLACK = 30
    FG_RED = 31
    FG_GREEN = 32
    FG_YELLOW = 33
    FG_BLUE = 34
    FG_MAGENTA = 35
    FG_CYAN = 36
    FG_WHITE = 37

    BG_BLACK = 40
    BG_RED = 41
    BG_GREEN = 42
    BG_YELLOW = 44
    BG_BLUE = 44
    BG_MAGENTA = 45
    BG_CYAN = 46
    BG_WHITE = 47

    @staticmethod
    def encode(*attrs):
        return ''.join(['\033[', ';'.join(str(a) for a in attrs), 'm'])

    @staticmethod
    def wrap(text, attrs=None):
        if not attrs:
            attrs = [Style.RESET]
        start = Style.encode(*attrs)
        end = Style.encode(Style.RESET)
        return ''.join([start, str(text), end])


class Commander(object):
    def __init__(self, onerr=None):
        self.parser = argparse.ArgumentParser()
        self.commands_parser = self.parser.add_subparsers()
        self.onerr = onerr
        self.commands = {}

    def make_command(self, name, action):
        parser = self.commands_parser.add_parser(name)
        parser.add_argument('--ACTION', dest='action', action='store_const',
                            const=action, default=action)
        self.commands[name] = parser
        return parser

    def format_help(self):
        return self.parser.format_help()

    def parse(self, command):
        args = []
        arg = []
        string_tokens = ('"', '"')
        state = None

        def take_arg(arg):
            if arg:
                args.append(''.join(arg))
                return []
            return arg

        for ch in command:
            if state is None:
                if ch in string.whitespace and arg:
                    arg = take_arg(arg)
                elif ch in string_tokens:
                    state = ch
                else:
                    arg.append(ch)
            elif state in string_tokens:
                if ch == state:
                    arg = take_arg(arg)
                    state = None
                else:
                    arg.append(ch)
        arg = take_arg(arg)
        err = None
        parsed = None
        try:
            parsed = self.parser.parse_args(args)
        except SystemExit as e:
            err = e
        except Exception as e:
            err = e
        return err, parsed

    def run(self, command, **kwargs):
        (err, parsed) = self.parse(command)
        if err and self.onerr:
            return self.onerr('Invalid command: {}'.format(command), **kwargs)
        elif parsed:
            return parsed.action(parsed, **kwargs)


class Move(object):
    superior = None
    inferior = None

    def __repr__(self):
        return Style.wrap(self.__class__.__name__,
                          [Style.BG_WHITE, Style.FG_BLACK, Style.BOLD])

    def __cmp__(self, other):
        if isinstance(other, self.superior):
            return -1
        elif isinstance(other, self.inferior):
            return 1
        elif isinstance(other, self.__class__):
            return 0
        else:
            raise TypeError('Can\'t compare {0} with {1}'.format(self, other))


class ROCK(Move):
    def __init__(self):
        self.superior = PAPER
        self.inferior = SCISSORS


class PAPER(Move):
    def __init__(self):
        self.superior = SCISSORS
        self.inferior = ROCK


class SCISSORS(Move):
    def __init__(self):
        self.superior = ROCK
        self.inferior = PAPER


class Game(object):
    winning_score = 3

    def __init__(self, name, lobby):
        self.name = name
        self.lobby = lobby
        self.winner = None
        self.players = set()
        self.moves = {}
        self.reset_score()

    def reset_score(self):
        self.score = defaultdict(lambda: 0)

    def add_player(self, player):
        if self.full:
            player.prompt('Game is already full')
            return None
        self.players.add(player)
        return True

    def remove_player(self, player):
        if self.moves:
            self.end_game()
        else:
            players = list(self.players)
            self.players.remove(player)
            for p in players:
                p.prompt()

    def other_player(self, player):
        diff = self.players - {player}
        if diff:
            (result,) = diff
        else:
            result = None
        return result

    def try_run(self):
        if self.full:
            self.prompt_move()
            return True
        else:
            return False

    def prompt_move(self, player=None):
        if player is not None:
            ps = [self.players[player]]
        else:
            ps = self.players
        for p in ps:
            p.prompt('\nMake your move!')

    @property
    def full(self):
        return len(self.players) >= 2

    @property
    def gameover(self):
        return self.winner is not None

    def end_game(self):
        for p in self.players:
            p.game = None
            p.prompt()
        del self.lobby.games[self.name]

    def sendall(self, msg):
        for p in self.players:
            p.send(msg)

    def show_score(self):
        return '\n'.join('{0}: {1}'.format(p, self.score[p])
                         for p in self.players)

    def play(self, player, move):
        other = self.other_player(player)
        if player not in self.players:
            player.send('You aren\'t a player in this game')
            return

        if self.gameover:
            player.send('Player {} already won'.format(self.winner))

        if not self.full:
            player.send('Wait until the game is full before playing...')

        move_upper = move.upper()
        if move_upper in ('R', 'ROCK'):
            self.moves[player] = ROCK()
        elif move_upper in ('P', 'PAPER'):
            self.moves[player] = PAPER()
        elif move_upper in ('S', 'SCISSORS'):
            self.moves[player] = SCISSORS()
        elif move_upper == 'EXIT':
            self.remove_player(player)
            return
        else:
            player.prompt(''.join([
                'Invalid move: "{}"'.format(move),
                ' Choose one of: (R)OCK, (P)APER or (S)CISSORS'
            ]))
            return

        if len(self.moves) == 2:
            self.sendall('\n')
            _players = list(self.players)
            for p1, p2 in zip(_players, reversed(_players)):
                p1.send('{0} threw {1}'.format(p2, self.moves[p2]))

            winner = None
            if self.moves[player] > self.moves[other]:
                winner = player
            elif self.moves[other] > self.moves[player]:
                winner = other
            if winner is not None:
                self.score[winner] += 1
                if self.score[winner] >= self.winning_score:
                    self.winner = winner
                    self.sendall('\n'.join([
                        'Player {} wins the game!'.format(winner),
                        self.show_score(),
                    ]))
                else:
                    self.sendall('\n'.join([
                        'Player {} wins the round!'.format(winner),
                        self.show_score(),
                    ]))
            else:
                self.sendall('Tie')

            self.moves = {}
            if self.gameover:
                self.end_game()
            else:
                self.prompt_move()
        else:
            player.send('Waiting for other player to play...')

    def __repr__(self):
        s = [Style.wrap(self.name, [Style.FG_GREEN])]
        if self.full:
            s.append(Style.wrap('(FULL)', [Style.FG_RED, Style.BOLD]))
        if len(self.players):
            s.append('with')
            if len(self.players) == 2:
                s.append('{0}, {1}'.format(*list(self.players)))
            else:
                (p,) = self.players
                s.append(str(p))
        return ' '.join(s)


class Lobby(object):
    def __init__(self):
        self.games = OrderedDict()

    def new_game(self, name):
        if name in self.games:
            return 'Name "{}" taken'.format(name)
        game = Game(name, lobby=self)
        self.games[name] = game
        return game

    def list_games(self):
        ls = '\n'.join('    {0}'.format(g) for _, g in self.games.iteritems())
        if not ls:
            ls = 'No games'
        return ls

    def get_game(self, name):
        return self.games.get(name)


class Player(object):
    def __init__(self, sock, lobby):
        self.socket = sock
        self.lobby = lobby
        self.name = None
        self.game = None
        self.reset_notifications_messages()

    def reset_notifications_messages(self):
        self.messages = []
        self.notifications = []

    def notify(self, message):
        self.notifications.append(message)

    def message(self, message):
        self.messages.append(message)

    def send_notifications_messages(self):
        message = '\n'.join(self.notifications + self.messages)
        if message:
            self.prompt(message)
        self.reset_notifications_messages()

    def prompt(self, txt=''):
        if txt and not txt.endswith('\n'):
            txt += '\n'
        game_prompt = ''
        if self.game:
            if self.game.full:
                game_prompt = 'playing {0} against {1} '.format(
                    Style.wrap(self.game.name, [Style.FG_GREEN]),
                    self.game.other_player(self))
            else:
                return
        txt += '{}> '.format(game_prompt)
        self.socket.send(txt)

    def prompt_name(self):
        self.socket.send('Please enter your name: ')

    def send(self, txt):
        if txt and not txt.endswith('\n'):
            txt += '\n'
        self.socket.send(txt)

    def create_game(self, name):
        game = self.lobby.new_game(name)
        if isinstance(game, basestring):
            msg = game
            self.prompt(msg)
            return
        self.join_game(name)
        return game

    def join_game(self, name):
        game = self.lobby.get_game(name)
        if not game:
            self.prompt('No game "{}"'.format(name))
        elif game.full:
            self.prompt('Game is full')
        else:
            game.add_player(self)
            self.game = game
            if not self.game.try_run():
                self.send('Waiting for other player...')

    def exit_game(self):
        if self.game:
            self.game = None
            game.remove_player(self)

    def play(self, move):
        self.game.play(self, move)

    def fileno(self):
        return self.socket.fileno()

    def __repr__(self):
        return Style.wrap(self.name, [Style.FG_BLUE])


class Server(object):
    argparser = None

    def __init__(self, host, port):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        print 'Binding to {0}:{1}'.format(host, port)
        self.socket.bind((host, int(port)))
        self.socket.listen(1)
        self.read_list = [self]
        self.write_list = []
        self.lobby = Lobby()

        self.commander = Commander(onerr=self.commander_err)
        self.commander.make_command('?', self.show_help)
        self.commander.make_command('list', self.list_games)
        self.commander.make_command('who', self.list_players)
        create_cmd = self.commander.make_command('create', self.create_game)
        create_cmd.add_argument('name', action='store')
        join_cmd = self.commander.make_command('join', self.join_game)
        join_cmd.add_argument('name', action='store')

    def commander_err(self, err, player):
        player.notifications.append(err)
        self.show_help(None, player)

    def show_help(self, _, player):
        player.notifications.append(self.commander.format_help())

    def list_games(self, _, player):
        player.notify(self.lobby.list_games())

    def list_players(self, _, player):
        players = []
        for p in self.read_list:
            if isinstance(p, Player):
                player_text = ['    ', str(p)]
                if p.game:
                    player_text.append(' in ')
                    player_text.append(Style.wrap(
                        p.game.name, [Style.FG_GREEN]))
                players.append(''.join(player_text))
        player.prompt('\n'.join(players))

    def create_game(self, args, player):
        name = args.name
        game = player.create_game(name)
        self.notify(
            '{0} created game {1}'.format(
                player, Style.wrap(game.name, [Style.FG_GREEN])),
            author=player)

    def join_game(self, args, player):
        name = args.name
        player.join_game(name)
        self.notify(
            '{0} joined game {1}'.format(
                player, Style.wrap(name, [Style.FG_GREEN])),
            author=player)

    def notify(self, message, author=None):
        for player in self.write_list:
            if player is not author:
                player.notifications.append(message)

    def chat(self, message, from_, to=None):
        if to:
            to.messages.append('{0} to you: {1}'.format(from_, message))
        else:
            for player in self.write_list:
                if player is not from_:
                    player.messages.append('{0}: {1}'.format(from_, message))

    def serve(self):
        while True:
            readable, writable, _ = select.select(
                self.read_list, self.write_list, [])
            for sock in writable:
                if isinstance(sock, Player):
                    sock.send_notifications_messages()
            for sock in readable:
                if sock is self:
                    new_client, _ = self.socket.accept()
                    player = Player(new_client, self.lobby)
                    self.connect(player)
                    player.prompt_name()
                elif isinstance(sock, Player):
                    player = sock
                    data = player.socket.recv(1024)
                    if not data:
                        self.disconnect(player)
                        continue
                    else:
                        data = data.strip()
                    if not player.name:
                        player.name = data
                        player.prompt(Style.wrap(
                            'Welcome to Rock Paper Scissors! Type "?" '
                            'for help',
                            [Style.FG_MAGENTA]))
                        continue
                    if player.game:
                        player.play(data)
                    else:
                        self.commander.run(data, player=player)

    def connect(self, client):
        self.read_list.append(client)
        self.write_list.append(client)

    def disconnect(self, client):
        self.read_list.remove(client)
        self.write_list.remove(client)
        if isinstance(client, Player):
            pass

    def fileno(self):
        return self.socket.fileno()


def main(host, port):
    """Start a rock-paper-scissors server"""
    server = Server(host, port)
    server.serve()


if __name__ == '__main__':
    main(*sys.argv[1:])
