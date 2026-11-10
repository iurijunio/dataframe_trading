"""Valida somente o harness; não importa produção nem acessa dados operacionais."""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib
import unittest

RAIZ = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('guarda_codex', RAIZ / '.codex/hooks/guard.py')
guarda = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guarda)


class Harness(unittest.TestCase):
    def test_detalhes_codex_ficam_fora_do_nucleo_compartilhado(self):
        nucleo = (RAIZ / 'AGENTS.md').read_text(encoding='utf-8')
        for exclusivo in ['.codex/', '.agents/skills/', '.codex/README.md', 'Sol', 'Luna', 'Terra', 'Astra']:
            self.assertNotIn(exclusivo, nucleo)
        config = tomllib.loads((RAIZ / '.codex/config.toml').read_text(encoding='utf-8'))
        self.assertIn('.codex/INSTRUCTIONS.md', config['developer_instructions'])
        self.assertTrue((RAIZ / '.codex/INSTRUCTIONS.md').is_file())

    def test_configuracao_e_modelos(self):
        config = tomllib.loads((RAIZ / '.codex/config.toml').read_text(encoding='utf-8'))
        self.assertEqual(config['model'], 'gpt-6.1-sol')
        self.assertEqual(config['model_reasoning_effort'], 'medium')
        self.assertEqual(config['agents']['default_subagent_model'], 'gpt-6-luna')
        self.assertEqual(config['agents']['max_concurrent_threads_per_session'], 3)
        esperados = {'tester': 'gpt-6-luna', 'explorer': 'gpt-6-luna',
                     'mutation': 'gpt-6-luna', 'documenter': 'gpt-6-luna',
                     'implementer': 'gpt-6.1-terra', 'ui-designer': 'gpt-6.1-terra',
                     'reviewer': 'gpt-6.1-sol', 'auditor': 'gpt-6-astra',
                     'architect': 'gpt-6-astra'}
        agentes = list((RAIZ / '.codex/agents').glob('*.toml'))
        self.assertEqual(len(agentes), len(esperados))
        for arquivo in agentes:
            agente = tomllib.loads(arquivo.read_text(encoding='utf-8'))
            self.assertEqual(agente['model'], esperados[agente['name']])
            self.assertTrue(agente['description'])
            self.assertTrue(agente['developer_instructions'])
            self.assertIn(agente['model_reasoning_effort'], {'medium', 'high'})
            self.assertNotIn('carregam ao abrir', agente['developer_instructions'])

    def test_instructions_and_skills_are_independent(self):
        instructions = list((RAIZ / '.codex/instructions').glob('*.md'))
        self.assertEqual(len(instructions), 8)
        for arquivo in instructions:
            self.assertIn('paths:', arquivo.read_text(encoding='utf-8'))
        for arquivo in (RAIZ / '.agents/skills').glob('*/SKILL.md'):
            texto = arquivo.read_text(encoding='utf-8')
            self.assertNotIn('.claude/', texto)
            for referencia in re.findall(r'`((?:\.codex|tests)/[\w/.-]+\.(?:toml|py))`', texto):
                self.assertTrue((RAIZ / referencia).is_file(), referencia)

    def test_instructions_cover_modularized_packages(self):
        pacotes_por_regra = {
            'capture-paper': ('core/leitura/', 'ui/cb_operacao/', 'ui/components/operacao/'),
            'orders': ('ui/components/ordens/', 'ui/components/ao_vivo/'),
        }
        for regra, pacotes in pacotes_por_regra.items():
            texto = (RAIZ / f'.codex/instructions/{regra}.md').read_text(encoding='utf-8')
            cabecalho = texto.split('---')[1]
            caminhos = re.findall(r'^\s*-\s*"([^"]+)"', cabecalho, re.M)
            for pacote in pacotes:
                with self.subTest(regra=regra, pacote=pacote):
                    self.assertIn(pacote + '**', caminhos)

    def test_limite_nucleo_inclusive_crlf(self):
        texto = (RAIZ / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertLessEqual(len(texto.replace('\n', '\r\n').encode('utf-8')), 9000)

    def test_servicos_e_mt5_bloqueados_sem_executar(self):
        for comando in ['python captura.py', 'cmd /c iniciar.bat',
                        '.venv/Scripts/python.exe ordens_real.py',
                        'python -c "import MetaTrader5"', 'py -c "import MetaTrader5"',
                        'py.exe -c "import MetaTrader5"', 'git clean -fdx']:
            with self.subTest(comando=comando):
                self.assertTrue(guarda.avaliar_evento({'tool_name': 'Bash', 'tool_input': {'command': comando}}, aberto=lambda: False))

    def test_testes_e_leitura_permitidos(self):
        for comando in ['git status', 'git diff -- captura.py',
                        '.venv/Scripts/python.exe -m pytest -q tests/test_ordens_real.py']:
            self.assertIsNone(guarda.avaliar_evento({'tool_name': 'Bash', 'tool_input': {'command': comando}}, aberto=lambda: False))

    def test_alias_exec_command(self):
        self.assertTrue(guarda.avaliar_evento({'tool_name': 'exec_command', 'tool_input': {'cmd': 'python captura.py'}}, aberto=lambda: False))

    def test_patch_diario_remocao_e_renomeacao(self):
        for patch in ['*** Delete File: data/ao_vivo/ordens/dia.jsonl\n',
                      '*** Update File: x.txt\n*** Move to: data/ao_vivo/ordens/dia.jsonl\n']:
            self.assertTrue(guarda.avaliar_evento({'tool_name': 'apply_patch', 'tool_input': {'command': patch}}))

    def test_patch_com_mencao_no_teste_permitido(self):
        patch = '*** Update File: tests/test_x.py\n+CAMINHO = "data/ao_vivo/ordens/dia.jsonl"\n'
        self.assertIsNone(guarda.avaliar_evento({'tool_name': 'apply_patch', 'tool_input': {'command': patch}}))

    def test_patch_script_mt5_fora_do_core_bloqueado(self):
        patch = '*** Add File: scripts/avulso.py\n+import MetaTrader5\n'
        self.assertTrue(guarda.avaliar_evento({'tool_name': 'apply_patch', 'tool_input': {'command': patch}}))

    def test_app_duplicado(self):
        evento = {'tool_name': 'Bash', 'tool_input': {'command': '.venv/Scripts/python.exe ui/app.py'}}
        self.assertTrue(guarda.avaliar_evento(evento, aberto=lambda: True))
        self.assertIsNone(guarda.avaliar_evento(evento, aberto=lambda: False))

    def test_app_duplicado_lancadores_powershell(self):
        for comando in ['py ui/app.py', '& ".venv/Scripts/python.exe" ui/app.py',
                        '.venv/Scripts/python.exe -u ui/app.py']:
            with self.subTest(comando=comando):
                self.assertTrue(guarda.avaliar_evento({'tool_name': 'Bash', 'tool_input': {'command': comando}}, aberto=lambda: True))

    def test_preview_remoto_com_app_aberto(self):
        evento = {'tool_name': 'mcp__remote-devices__Claude_Browser__preview_start', 'tool_input': {'name': 'dataframe'}}
        self.assertTrue(guarda.avaliar_evento(evento, aberto=lambda: True))
        self.assertIsNone(guarda.avaliar_evento(evento, aberto=lambda: False))

    def test_contrato_json_hook(self):
        # O comando é dado de entrada do hook, nunca é executado.
        resultado = subprocess.run([sys.executable, str(RAIZ / '.codex/hooks/guard.py')],
                                   input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'python captura.py'}}),
                                   text=True, encoding='utf-8', capture_output=True, check=True)
        saida = json.loads(resultado.stdout)['hookSpecificOutput']
        self.assertEqual(saida['hookEventName'], 'PreToolUse')
        self.assertEqual(saida['permissionDecision'], 'deny')

    def test_registro_hook(self):
        config = json.loads((RAIZ / '.codex/hooks.json').read_text(encoding='utf-8'))
        hook = config['hooks']['PreToolUse'][0]
        self.assertIn('Bash', hook['matcher'])
        self.assertIn('apply_patch', hook['matcher'])
        self.assertIn('.codex/hooks/guard.py', hook['hooks'][0]['command'])
        self.assertNotIn('.claude', hook['hooks'][0]['command'])

    @unittest.skipUnless(sys.platform == 'win32', 'O comando do harness usa PowerShell no Windows')
    def test_comando_registrado_em_subpasta(self):
        config = json.loads((RAIZ / '.codex/hooks.json').read_text(encoding='utf-8'))
        comando = config['hooks']['PreToolUse'][0]['hooks'][0]['command']
        resultado = subprocess.run(comando, cwd=RAIZ / 'core',
                                   input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'git clean -fdx'}}),
                                   text=True, encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(resultado.stdout)['hookSpecificOutput']['permissionDecision'], 'deny')


if __name__ == '__main__':
    unittest.main()
