"""BOT TERRARIA DISCORD — BETA."""
import asyncio
import logging
from pathlib import Path

import discord
from discord import app_commands
from config import Config
from terraria import Terraria, validate_command

log = logging.getLogger("beta")


def authorized(interaction, config):
    if interaction.guild_id != config.guild_id or interaction.guild_id is None:
        return False
    return bool((config.admin_id and interaction.user.id == config.admin_id) or
                (config.role_id and any(role.id == config.role_id for role in getattr(interaction.user, 'roles', []))))


class Beta(discord.Client):
    def __init__(self, config):
        super().__init__(intents=discord.Intents.none(),
                         allowed_mentions=discord.AllowedMentions.none())
        self.config = config
        self.terraria = Terraria(config)
        self.tasks = []
        self.tree = app_commands.CommandTree(self)
        self.tree.interaction_check = self.check_interaction
        self.tree.on_error = self.command_error
        self.register_commands()

    def safe_text(self, text):
        for secret in self.config.secrets:
            text = text.replace(secret, '[oculto]')
        return discord.utils.escape_mentions(discord.utils.escape_markdown(text))

    async def reply(self, interaction, text):
        text = self.safe_text(text) or 'Nenhuma informação disponível.'
        for offset in range(0, len(text), 1900):
            sender = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
            await sender(text[offset:offset + 1900], ephemeral=True,
                         allowed_mentions=discord.AllowedMentions.none())

    async def check_interaction(self, interaction):
        if interaction.guild_id != self.config.guild_id:
            await self.reply(interaction, 'Comando indisponível neste servidor ou em mensagens privadas.')
            return False
        return True

    async def command_error(self, interaction, error):
        log.error('Falha em comando Discord (%s)', type(error).__name__)
        await self.reply(interaction, 'Não foi possível executar. Confira conexão, configuração e permissões.')

    def register_commands(self):
        t, c = self.terraria, self.config

        @self.tree.command(name='status', description='Status observado do servidor e da conexão do bot')
        async def status(i: discord.Interaction):
            state = {True: 'ONLINE', False: 'OFFLINE', None: 'DESCONHECIDO / INICIANDO'}[t.online]
            if c.mode == 'tcp':
                state += ' (somente TCP; não confirma identidade ou saúde do Terraria)'
            count = str(len(t.players)) if t.online and t.players_known else 'Indisponível'
            await self.reply(i, f'{state}\nHost público: {c.public_host}\nPorta: {c.port}\n'
                             f'Players observados: {count}\nMáximo detectado: {t.maxplayers or "Indisponível"}\n'
                             f'Método: {c.mode}\nDiscord: {"conectado" if self.is_ready() else "desconectado"}')

        @self.tree.command(name='players', description='Jogadores observados desde o início do processo')
        async def players(i: discord.Interaction):
            if not t.online or not t.players_known:
                await self.reply(i, 'Lista indisponível; exige console local online com mensagens reconhecidas.')
                return
            names = sorted(t.players, key=str.casefold)
            await self.reply(i, 'PLAYERS OBSERVADOS\n' + '\n'.join(f'{n}. {name}' for n, name in enumerate(names, 1))
                             + f'\nTotal: {len(names)}\nFonte: entradas/saídas do console nesta execução.')

        @self.tree.command(name='player', description='Informações observadas de um jogador online')
        @app_commands.describe(nome='Nome exato do personagem')
        async def player(i: discord.Interaction, nome: str):
            data = t.players.get(nome) if t.online and t.players_known else None
            if not data:
                await self.reply(i, 'Jogador não observado online ou dados indisponíveis. Use o nome exato de /players.')
                return
            await self.reply(i, f'{nome}\nEntrada observada: {data["since"]}\n'
                             f'Mensagens de morte reconhecidas: {data["deaths"]} (contagem parcial)\n'
                             'Vida, inventário, posição e mortes totais: indisponíveis.')

        @self.tree.command(name='events', description='Últimos dez eventos detectados nesta execução')
        async def events(i: discord.Interaction):
            await self.reply(i, '\n'.join(f'{ts} | {kind}: {text}' for ts, kind, text in list(t.events)[-10:])
                             or 'Nenhum evento detectado nesta execução.')

        @self.tree.command(name='bosses', description='Textos de bosses/eventos observados, com cobertura parcial')
        async def bosses(i: discord.Interaction):
            lines = [f'{ts}: {text}' for ts, kind, text in t.events if kind == 'BOSS/EVENTO'][-10:]
            await self.reply(i, ('\n'.join(lines) or 'Nenhum texto reconhecido de boss/evento.') +
                             '\nLIMITADO: somente mensagens emitidas no console; não informa bosses ativos, '
                             'progressão nem confirma ausência. Sem eventos internos via TCP.')

        @self.tree.command(name='world', description='Mundo configurado, sem inventar dados internos')
        async def world(i: discord.Interaction):
            world_file = c.server_values.get('world')
            await self.reply(i, f'Arquivo configurado: {Path(world_file).name if world_file else "Indisponível"}\n'
                             'Fonte: configuração local, não leitura do mundo em jogo.\n'
                             'Dificuldade atual, bioma, progressão e hardmode: indisponíveis.')

        @self.tree.command(name='server', description='Versão, método e limitações do servidor')
        async def server(i: discord.Interaction):
            await self.reply(i, f'Terraria Vanilla — BETA\nVersão detectada: {t.version or "Indisponível"}\n'
                             f'Método: {c.mode}\nConsole: {"local" if c.mode == "process" else "indisponível"}\n'
                             'Process: observa stdout e controla stdin do processo iniciado pelo bot.\n'
                             'TCP: apenas alcançabilidade da porta; não obtém players, mundo ou eventos.\n'
                             'Mortes/bosses: reconhecimento parcial de textos, sem garantia de emissão.')

        @self.tree.command(name='help', description='Ajuda da Beta')
        async def help_command(i: discord.Interaction):
            await self.reply(i, 'BOT TERRARIA DISCORD — BETA\n/status /players /player <nome>\n'
                             '/events /bosses /world /server /help\n/console <comando>: somente ID/cargo autorizado.\n'
                             'Console: help, playing, version, time, port, maxplayers, save, dawn, noon, '
                             'dusk, midnight, settle, exit, say <texto>, kick/ban <nome>.\n'
                             'Respostas privadas; notificações no canal configurado. Histórico só em memória.')

        @self.tree.command(name='console', description='Admin autorizado: enviar um comando ao console Vanilla local')
        @app_commands.describe(comando='Comando Vanilla permitido; exit salva e desliga, sem reiniciar automaticamente')
        async def console(i: discord.Interaction, comando: str):
            if not authorized(i, c):
                await self.reply(i, 'Acesso negado. Configure DISCORD_ADMIN_ID ou DISCORD_ADMIN_ROLE_ID.')
                return
            try:
                command = validate_command(comando)
                await i.response.defer(ephemeral=True)
                await t.send(command)
            except (ValueError, RuntimeError) as exc:
                await self.reply(i, str(exc))
                return
            except OSError:
                await self.reply(i, 'Console desconectou durante o envio; execução não confirmada.')
                return
            log.info('Console autorizado: usuário %s, comando %s', i.user.id, command.split()[0])
            await self.reply(i, 'Comando enviado ao stdin do Vanilla. Envio não garante execução. '
                             'Saída bruta não é repassada por segurança; consulte /status e /events.')

    async def setup_hook(self):
        guild = discord.Object(id=self.config.guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        self.channel = await self.fetch_channel(self.config.channel_id)
        if not isinstance(self.channel, discord.TextChannel) or self.channel.guild.id != self.config.guild_id:
            raise ValueError('DISCORD_CHANNEL_ID precisa ser um canal de texto do servidor configurado')
        await self.channel.send('BOT TERRARIA DISCORD — BETA iniciado. Monitoramento em preparação.')
        self.tasks = [asyncio.create_task(self.monitor()), asyncio.create_task(self.notify())]

    async def monitor(self):
        await self.wait_until_ready()
        await self.terraria.run()

    async def notify(self):
        while True:
            timestamp, kind, text = await self.terraria.notifications.get()
            while True:
                await self.wait_until_ready()
                try:
                    await self.channel.send(self.safe_text(f'{kind}\n{text}\n{timestamp}')[:1900])
                    break
                except (discord.HTTPException, OSError):
                    log.warning('Notificação pendente: verifique rede, canal e permissões; tentando novamente')
                    await asyncio.sleep(self.config.interval)

    async def close(self):
        self.terraria.stopping = True
        await self.terraria.stop_process()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await super().close()

    async def on_ready(self):
        log.info("Conectado ao Discord")

    async def on_disconnect(self):
        log.warning("Discord desconectado; a biblioteca tentará reconectar")


def main():
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    try:
        config = Config()
        config.validate_discord()
        client = Beta(config)
        client.run(config.token, log_handler=None, reconnect=True)
    except discord.LoginFailure:
        log.error("Token Discord inválido")
        return 1
    except ValueError as exc:
        log.error('%s', exc)
        return 1
    except (discord.HTTPException, OSError) as exc:
        log.error('Falha de conexão/permissões (%s); confira configuração local', type(exc).__name__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
