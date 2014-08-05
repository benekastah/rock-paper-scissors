# pylint: disable=missing-docstring
# Chat program
import select
import socket
from collections import OrderedDict

HOST = '0.0.0.0'
PORT = 1338


class ROCK(object):
    name = 'rock'

    def __cmp__(self, other):
        if isinstance(other, PAPER):
            return -1
        elif isinstance(other, SCISSORS):
            return 1
        else:
            return 0


class PAPER(object):
    name = 'paper'

    def __cmp__(self, other):
        if isinstance(other, SCISSORS):
            return -1
        elif isinstance(other, ROCK):
            return 1
        else:
            return 0


class SCISSORS(object):
    name = 'scissors'

    def __cmp__(self, other):
        if isinstance(other, ROCK):
            return -1
        elif isinstance(other, PAPER):
            return 1
        else:
            return 0


class Game(object):
    winning_score = 3

    def __init__(self, name):
        self.name = name
        self.winner = None
        self.players = tuple()
        self.moves = {}
        self.reset_score()

    def reset_score(self):
        self.score = {0: 0, 1: 0}

    def add_player(self, player):
        if self.full:
            raise Exception('Game is already full')
        self.players += (player,)
        return len(self.players) - 1

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

    def sendall(self, msg):
        for p in self.players:
            p.send(msg)

    def play(self, player, move):
        if self.winner is not None:
            self.players[player].send(
                'Player {} already won'.format(self.winner))

        if not self.full:
            self.players[player].send(
                'Wait until the game is full before playing...')

        if move in ('r', 'rock'):
            self.moves[player] = ROCK()
        elif move in ('p', 'paper'):
            self.moves[player] = PAPER()
        elif move in ('s', 'scissors'):
            self.moves[player] = SCISSORS()
        else:
            self.players[player].prompt(''.join([
                'Invalid move: "{}"'.format(move),
                ' Choose one of: (r)ock, (p)aper or (s)cissors'
            ]))
            return

        if len(self.moves) == 2:
            self.sendall('\n')
            self.players[0].send(
                'Player 1 threw {}'.format(self.moves[1].name))
            self.players[1].send(
                'Player 0 threw {}'.format(self.moves[0].name))

            winner = None
            if self.moves[0] > self.moves[1]:
                self.score[0] += 1
                winner = 0
            elif self.moves[1] > self.moves[0]:
                self.score[1] += 1
                winner = 1
            if winner is not None:
                if self.score[winner] >= self.winning_score:
                    self.winner = winner
                    self.sendall('\n'.join([
                        'Player {} wins the game!'.format(winner),
                        'Final score: {}'.format(self.score),
                    ]))
                else:
                    self.sendall('\n'.join([
                        'Player {} wins the round!'.format(winner),
                        'Score: {}'.format(self.score),
                    ]))
            else:
                self.sendall('Tie')

            self.moves = {}
            if self.winner is None:
                self.prompt_move()
        else:
            self.players[player].send('Waiting for other player to play...')


class Lobby(object):
    def __init__(self):
        self.games = OrderedDict()

    def new_game(self, name):
        if name in self.games:
            return Exception('Name "{}" taken'.format(name))
        game = Game(name)
        self.games[name] = game
        return game

    def list_games(self):
        ls = '\n'.join('- {} ({})'.format(n, 'full' if g.full else 'open')
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
        ])


class Player(object):
    def __init__(self, sock, lobby):
        self.socket = sock
        self.lobby = lobby
        self.player_id = None
        self.game = None

    def prompt(self, txt=''):
        if txt and not txt.endswith('\n'):
            txt += '\n'
        game_prompt = ''
        if self.game:
            game_prompt = 'player {0} in {1}'.format(
                self.player_id, self.game.name)
        txt += '{} > '.format(game_prompt)
        self.socket.send(txt)

    def send(self, txt):
        if txt and not txt.endswith('\n'):
            txt += '\n'
        self.socket.send(txt)

    def create_game(self, name):
        try:
            self.lobby.new_game(name)
        except Exception as e:
            self.socket.send(str(e) + '\n')
        self.join_game(name)

    def join_game(self, name):
        game = self.lobby.get_game(name)
        if not game:
            self.prompt('No game "{}"'.format(name))
        elif game.full:
            self.prompt('Game is full')
        else:
            self.player_id = game.add_player(self)
            self.game = game
            if not self.game.try_run():
                self.send('Waiting for other player...')

    def play(self, move):
        self.game.play(self.player_id, move)

    def fileno(self):
        return self.socket.fileno()


def main():
    """Start a rock-paper-scissors server"""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
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
                player.send(
                    'Welcome to Rock Paper Scissors! Type "?" for help')
                player.prompt()
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
                    if data == '?':
                        player.prompt(lobby.help())
                    elif data == 'l':
                        player.prompt(lobby.list_games())
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
    main()
