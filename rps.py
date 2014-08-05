# pylint: disable=missing-docstring
from collections import OrderedDict, defaultdict
import select
import socket
import sys


class Move(object):
    superior = None
    inferior = None

    def __repr__(self):
        return self.__class__.__name__

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

    def other_player(self, player):
        diff = self.players - {player}
        (result,) = diff
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
        if player not in self.players:
            player.send('You aren\'t a player in this game')
            return

        if self.gameover:
            player.send('Player {} already won'.format(self.winner))

        if not self.full:
            player.send('Wait until the game is full before playing...')

        move = move.upper()
        if move in ('R', 'ROCK'):
            self.moves[player] = ROCK()
        elif move in ('P', 'PAPER'):
            self.moves[player] = PAPER()
        elif move in ('S', 'SCISSORS'):
            self.moves[player] = SCISSORS()
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
            other = self.other_player(player)
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
        return self.name


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
        ls = '\n'.join('    {} ({})'.format(n, 'full' if g.full else 'open')
                       for n, g in self.games.iteritems())
        if not ls:
            ls = 'No games'
        return ls

    def get_game(self, name):
        return self.games.get(name)

    def help(self):
        return '\n'.join([
            'Commands:',
            '    ?: show this text',
            '    c <name>: create new game with <name>',
            '    j <name>: join existing game with <name>',
            '    l: list games',
            '    who: list players',
        ])


class Player(object):
    def __init__(self, sock, lobby):
        self.socket = sock
        self.lobby = lobby
        self.name = None
        self.game = None

    def prompt(self, txt=''):
        if txt and not txt.endswith('\n'):
            txt += '\n'
        game_prompt = ''
        if self.game:
            game_prompt = 'playing "{0}" against "{1}" '.format(
                self.game.name, self.game.other_player(self))
        txt += '{}> '.format(game_prompt)
        self.socket.send(txt)

    def prompt_name(self):
        self.socket.send('Please enter your name: ')

    def send(self, txt):
        if txt and not txt.endswith('\n'):
            txt += '\n'
        self.socket.send(txt)

    def create_game(self, name):
        msg = self.lobby.new_game(name)
        if isinstance(msg, basestring):
            self.prompt(msg)
            return
        self.join_game(name)

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

    def play(self, move):
        self.game.play(self, move)

    def fileno(self):
        return self.socket.fileno()

    def __repr__(self):
        return self.name


def main(host, port):
    """Start a rock-paper-scissors server"""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    print 'Binding to {0}:{1}'.format(host, port)
    server.bind((host, int(port)))
    server.listen(1)
    lobby = Lobby()
    read_list = [server]
    write_list = []

    def disconnect(sock):
        read_list.remove(sock)
        write_list.remove(sock)

    while True:
        readable, _, _ = select.select(read_list, [], [])
        for sock in readable:
            if sock is server:
                new_client, _ = server.accept()
                player = Player(new_client, lobby)
                read_list.append(player)
                write_list.append(player)
                player.prompt_name()
            elif isinstance(sock, Player):
                player = sock
                data = player.socket.recv(1024)
                if not data:
                    disconnect(player)
                    continue
                else:
                    data = data.strip()

                if player.game:
                    player.play(data)
                else:
                    if not player.name:
                        if data:
                            player.name = data
                            player.prompt('Welcome to Rock Paper Scissors! '
                                          'Type "?" for help')
                        else:
                            player.prompt_name()
                        continue

                    if data == '?':
                        player.prompt(lobby.help())
                    elif data == 'l':
                        player.prompt(lobby.list_games())
                    elif data == 'who':
                        players = ['    {}'.format(p) for p in read_list
                                   if isinstance(p, Player)]
                        player.prompt('\n'.join(p for p in players))
                    elif data.startswith('c '):
                        name = data[2:]
                        player.create_game(name)
                    elif data.startswith('j '):
                        player.join_game(data[2:])
                    else:
                        player.prompt('Unrecognized command: {}'.format(data))
            else:
                disconnect(sock)


if __name__ == '__main__':
    main(*sys.argv[1:])
