"""Transporte Vanilla: processo/console local ou sondagem TCP limitada."""
import asyncio
from collections import deque
from datetime import datetime, timezone
import logging
import os
import re

log = logging.getLogger('beta')
BOSSES = (
    'King Slime', 'Eye of Cthulhu', 'Eater of Worlds', 'Brain of Cthulhu',
    'Queen Bee', 'Skeletron', 'Deerclops', 'Wall of Flesh', 'Queen Slime',
    'The Twins', 'The Destroyer', 'Skeletron Prime', 'Plantera', 'Golem',
    'Duke Fishron', 'Empress of Light', 'Lunatic Cultist', 'Moon Lord', 'Mechdusa',
)
BOSS_LINE = re.compile(r'(' + '|'.join(map(re.escape, BOSSES)) + r') (?:has|have) (awoken|been defeated)!')
EVENT_LINES = {'The Blood Moon is rising...', 'A goblin army has arrived!', 'Martians are invading!'}


def validate_command(text):
    if not text or len(text) > 200 or not all(char.isprintable() for char in text) or ';' in text:
        raise ValueError('Use um único comando de até 200 caracteres, sem controles ou ponto e vírgula')
    verb, _, args = text.strip().partition(' ')
    verb, args = verb.lower(), args.strip()
    plain = {'help', 'playing', 'version', 'time', 'port', 'maxplayers', 'save',
             'dawn', 'noon', 'dusk', 'midnight', 'settle', 'exit'}
    if (verb in plain and not args) or (verb in {'say', 'kick', 'ban'} and args):
        return verb + (' ' + args if args else '')
    raise ValueError('Comando não permitido ou argumentos inválidos. Password e exit-nosave são bloqueados')


class Terraria:
    def __init__(self, config):
        self.config = config
        self.online = None
        self.process = None
        self.stopping = False
        self.manual_stop = False
        self.players = {}
        self.players_known = False
        self.version = None
        self.maxplayers = None
        self.events = deque(maxlen=50)
        self.notifications = asyncio.Queue(maxsize=100)

    def emit(self, kind, text):
        for secret in self.config.secrets:
            text = text.replace(secret, '[oculto]')
        event = (datetime.now(timezone.utc).strftime('%H:%M:%S UTC'), kind, text[:1200])
        self.events.append(event)
        if self.notifications.full():
            self.notifications.get_nowait()
            log.warning('Fila cheia; notificação mais antiga descartada')
        self.notifications.put_nowait(event)
        log.info('%s: %s', kind, event[2])

    async def probe(self):
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(self.config.host, self.config.port), 3)
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, TimeoutError):
            return False

    def handle_line(self, line):
        line = re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', line).strip('\ufeff\r\n >:')
        # Chat e mensagens de /console say nunca são interpretados como eventos.
        if not line or line.startswith(('<', '*')):
            return
        if line == 'Server started':
            self.online = True
            self.players.clear()
            self.players_known = True
            self.emit('SERVIDOR ONLINE', 'Console Vanilla confirmou: Server started')
        elif match := re.fullmatch(r'Terraria Server (v[\d.]+)', line):
            self.version = match[1]
        elif match := re.fullmatch(r'Player limit: (\d+)', line):
            self.maxplayers = int(match[1])
        elif self.online and (match := re.fullmatch(r'(.{1,40}) has (joined|left)\.', line)):
            name, action = match.groups()
            if action == 'joined' and name not in self.players:
                self.players[name] = {'since': datetime.now(timezone.utc).strftime('%H:%M:%S UTC'), 'deaths': 0}
                self.emit('PLAYER ENTROU', f'{name} entrou. Players observados: {len(self.players)}')
            elif action == 'left' and name in self.players:
                del self.players[name]
                self.emit('PLAYER SAIU', f'{name} saiu. Players observados: {len(self.players)}')
        elif self.online and (BOSS_LINE.fullmatch(line) or line in EVENT_LINES):
            self.emit('BOSS/EVENTO', f'Texto observado no console: {line}')
        elif line == 'Saving before exit...':
            self.emit('AVISO', 'Console informou: salvando antes de encerrar.')
        elif re.match(r'^(?:Unhandled Exception:|System\.[\w.]*Exception:)', line):
            self.emit('ERRO', 'Console reportou uma exceção; detalhes omitidos para não expor dados locais.')
        elif self.online:
            for name, player in self.players.items():
                if re.fullmatch(re.escape(name) + r' (?:was slain|was eviscerated|was murdered|drowned|burned to death)(?: by [^\r\n]+)?\.', line):
                    player['deaths'] += 1
                    self.emit('PLAYER MORREU', f'{name}: mensagem de morte observada no console.')
                    break

    async def run(self):
        while not self.stopping and not self.manual_stop:
            try:
                if self.config.mode == 'tcp':
                    reachable = await self.probe()
                    if reachable != self.online:
                        self.online = reachable
                        self.emit('TCP', 'Porta acessível; identidade Terraria não verificada.' if reachable
                                  else 'Porta inacessível; servidor desligado ou falha de rede/firewall.')
                else:
                    await self.run_process()
            except (OSError, ValueError, RuntimeError) as exc:
                self.online = None
                self.emit('ERRO', f'Falha no monitor ({type(exc).__name__}); nova tentativa automática.')
            if not self.stopping and not self.manual_stop:
                await asyncio.sleep(self.config.interval)

    async def run_process(self):
        # Não adotar nem controlar um servidor já em execução.
        if await self.probe():
            raise RuntimeError('Porta ocupada')
        env = {k: v for k, v in os.environ.items()
               if not k.startswith('DISCORD_') and k != 'TERRARIA_PASSWORD'}
        self.process = await asyncio.create_subprocess_exec(
            str(self.config.binary), '-config', str(self.config.server_config),
            '-port', str(self.config.port), '-noupnp',
            cwd=self.config.binary.parent, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, limit=262144)
        self.online = None
        self.players.clear()
        self.players_known = False
        self.maxplayers = None
        self.version = None
        self.emit('PROCESSO', 'Processo Vanilla iniciado; aguardando confirmação do console.')
        try:
            while raw := await self.process.stdout.readline():
                was_online = self.online
                self.handle_line(raw.decode('utf-8', errors='replace'))
                if self.online and not was_online:
                    await self.send('maxplayers')
            code = await self.process.wait()
            self.online = False
            self.players.clear()
            self.players_known = False
            self.emit('SERVIDOR OFFLINE', f'Processo encerrou (código {code}).')
        finally:
            await self.stop_process()

    async def send(self, command):
        command = validate_command(command)
        if self.config.mode != 'process' or not self.online or not self.process or self.process.returncode is not None:
            raise RuntimeError('Console indisponível: exige processo local iniciado e online')
        self.process.stdin.write((command + '\n').encode('utf-8'))
        await self.process.stdin.drain()
        if command == 'exit':
            self.manual_stop = True

    async def stop_process(self):
        if not self.process or self.process.returncode is not None:
            return
        try:
            self.process.stdin.write(b'exit\n')
            await self.process.stdin.drain()
            await asyncio.wait_for(self.process.wait(), 60)
        except (OSError, TimeoutError):
            log.error('Vanilla não encerrou normalmente; término forçado pode perder alterações')
            if self.process.returncode is None:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), 10)
                except TimeoutError:
                    self.process.kill()
                    await self.process.wait()
