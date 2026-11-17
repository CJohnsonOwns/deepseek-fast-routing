r"""A/B test of fast-routing settings for DeepSeek V4.1 Flash on Strata, in one model load.

It starts Strata with the patched engine, warms it up, then asks each question once per setting, rotating the order per
question so no setting always gets the warmest cache. Settings change live through DS4_CACHE_ROUTE_CTL (no reload).
Prints tokens/s, right answers, agreement with the first setting and the share of expert picks that had to wait for
the SSD (from the engine's own log).

  pip install requests psutil
  python ab_test.py --model-path D:\models\deepseek-v4.1-flash --engine ..\engine\strata-dsv41.exe
  python ab_test.py ... --configs "0,0,0;0.06,0,0;0.06,0.06,0.04" --n 5

A setting is "warm,vram,sticky" (see README). Takes about 2 minutes to load plus ~40 s per question per setting.
It refuses to start while another Strata or llama.cpp server is running, and stops its own Strata at the end.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

import psutil, requests

QUESTIONS = [  # (question, regex the final line must match): short, unambiguous, a mix of skills
    ("A shop sells pens at 3 for $4. How many dollars do 27 pens cost?", r"\b36\b"),
    ("What is 17 * 23 - 45?", r"\b346\b"),
    ("If today is Wednesday, what day of the week is it 100 days from now?", r"friday"),
    ("Alice is older than Bob. Bob is older than Carol. Dana is younger than Carol. Who is the second youngest?", r"carol"),
    ("What does this Python print?\n\nx = [1, 2, 3, 4, 5]\nprint(sum(v * v for v in x if v % 2))", r"\b35\b"),
    ("What does this Python print?\n\ns = 'mississippi'\nprint(len(set(s)), s.count('ss'))", r"\b4\s*,?\s*2\b"),
    ("Which planet in our solar system has the most confirmed moons as of 2025?", r"saturn"),
    ("What is the chemical symbol for tungsten?", r"\bw\b"),
    ("A train leaves at 09:40 and the trip takes 2 hours 35 minutes. At what time (HH:MM, 24-hour) does it arrive?", r"12:15"),
    ("How many distinct ways can you arrange the letters of the word LEVEL?", r"\b30\b"),
    ("In what year did the Berlin Wall fall?", r"1989"),
    ("What is the derivative of x^3 * ln(x) with respect to x? Give it in simplest form.",
     r"3\s*x\^?2\s*\*?\s*ln\s*\(?x\)?\s*\+\s*x\^?2|x\^?2\s*\(\s*3\s*ln"),
]
SYSTEM = "Answer briefly. Think as little as needed. End with one line: ANSWER: <final answer>"
WARMUP = "Write two sentences about why the sky looks blue."


def servers_up():
    return [(p.pid, p.info['name']) for p in psutil.process_iter(['name'])
            if (p.info['name'] or '').lower().startswith(('strata-ds', 'llama-server'))]


def default_store_gb():   # free RAM less 4 GB, at most total less 14 GB, at least 24 GB
    vm = psutil.virtual_memory()
    return max(24, min(int(vm.available / 1e9) - 4, int(vm.total / 1e9) - 14))


def ask(port, q, max_tokens):
    body = dict(model='deepseek', stream=True, temperature=0, max_tokens=max_tokens, reasoning_effort='low',
                messages=[dict(role='system', content=SYSTEM), dict(role='user', content=q)])
    first = last = None
    text, n = [], 0
    with requests.post(f'http://127.0.0.1:{port}/v1/chat/completions', json=body, stream=True, timeout=900) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line.startswith(b'data: ') or line == b'data: [DONE]':
                continue
            d = json.loads(line[6:])
            for ch in d.get('choices', []):
                delta = ch.get('delta', {})
                piece = (delta.get('content') or '') + (delta.get('reasoning_content') or '')
                if piece:
                    now = time.monotonic()
                    first = first or now
                    last = now
                    text.append(piece)
                    n += 1
            if d.get('usage'):
                n = d['usage'].get('completion_tokens', n)
    secs = (last - first) if first and last and last > first else 0.0
    return dict(text=''.join(text), tokens=n, secs=secs, tps=(n - 1) / secs if secs > 0 and n > 1 else 0.0)


def final_line(text):
    m = re.findall(r'ANSWER:\s*(.+)', text, flags=re.I)
    return (m[-1] if m else text[-200:]).strip()


def agree(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n / max(1, max(len(a), len(b)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model-path', required=True, help='the DeepSeek V4.1 Flash GGUF folder Strata loads')
    ap.add_argument('--engine', required=True, help='the patched strata-dsv41.exe')
    ap.add_argument('--strata', default='strata', help='the Strata command (default: strata on PATH)')
    ap.add_argument('--configs', default='0,0,0;0.06,0,0;0.06,0.06,0.04')
    ap.add_argument('--n', type=int, default=5, help='questions (of 12)')
    ap.add_argument('--tokens', type=int, default=500)
    ap.add_argument('--store-gb', type=int, default=0, help='RAM expert store (default: free RAM less 4 GB)')
    ap.add_argument('--context', type=int, default=32768)
    ap.add_argument('--port', type=int, default=8097)
    a = ap.parse_args()
    strata = shutil.which(a.strata) or a.strata
    configs = [tuple(float(x) for x in c.split(',')) for c in a.configs.split(';')]
    if servers_up():
        raise SystemExit(f'A model server is already running ({servers_up()}); stop it first.')
    engine = Path(a.engine).resolve()
    if not engine.is_file():
        raise SystemExit(f'No engine at {engine}')
    out = Path(__file__).resolve().parent / 'results'
    out.mkdir(exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    ctl = Path(tempfile.gettempdir()) / f'fast-routing-{stamp}.ctl'
    elog = out / f'engine-{stamp}.log'   # the engine's own lines (stderr), where its cache-route reports go
    ctl.write_text('0 0 0', encoding='ascii')
    env = dict(os.environ, STRATA_DSV41_EXE=str(engine), DS4_CACHE_ROUTE='0', DS4_CACHE_ROUTE_LOG='1',
               DS4_CACHE_ROUTE_CTL=str(ctl))
    qs = QUESTIONS[:a.n]
    runs = {c: [] for c in configs}
    order = [None]
    eng_log, mark = None, 0
    launch = [strata, 'launch', '--model-path', a.model_path, '--context', str(a.context), '--kv', 'int8',
              '--speed', 'full', '--vision', 'off', '--parallel', '1', '--set', f'ssd-cache={a.store_gb or default_store_gb()}',
              '--access', 'local', '--port', str(a.port), '--no-tui', '--yes', '--restart']
    try:
        print('Loading DeepSeek (about 2 minutes)...', flush=True)
        with open(elog, 'ab') as f:
            if subprocess.run(launch, env=env, stdout=f, stderr=subprocess.STDOUT).returncode:
                raise SystemExit(f'Strata did not start; see {elog}')
        for _ in range(600):
            try:
                if requests.get(f'http://127.0.0.1:{a.port}/health', timeout=3).status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(1)
        for p in psutil.process_iter(['name']):   # High priority: the CPU lane computes many experts on all cores
            if (p.info['name'] or '').lower().startswith('strata-ds'):
                try:
                    p.nice(psutil.HIGH_PRIORITY_CLASS if os.name == 'nt' else -5)
                except psutil.Error:
                    pass
        launch_logs = sorted(Path(os.environ.get('LOCALAPPDATA', Path.home())).glob('Strata/launch/*.engine.log'),
                             key=lambda p: p.stat().st_mtime)
        eng_log = launch_logs[-1] if launch_logs else None
        mark = eng_log.stat().st_size if eng_log else 0
        ask(a.port, WARMUP, 200)
        for qi, (q, rx) in enumerate(qs):
            rot = configs[qi % len(configs):] + configs[:qi % len(configs)]
            for c in rot:
                ctl.write_text(' '.join(str(x) for x in c), encoding='ascii')
                r = ask(a.port, q, a.tokens)
                r.update(right=bool(re.search(rx, final_line(r['text']), flags=re.I)), q=qi)
                runs[c].append(r)
                order.append(c)
                print(f'  q{qi + 1} {c}: {r["tps"]:5.2f} tok/s {"right" if r["right"] else "WRONG"}', flush=True)
        ctl.write_text('0 0 0', encoding='ascii')
        ask(a.port, 'Say OK.', 5)   # (its start prints the last question's report)
    finally:
        subprocess.run([strata, 'launch', '--stop'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    reports = []
    if eng_log is not None:
        txt = eng_log.read_bytes()[mark:].decode('utf-8', 'replace')
        reports = [(int(p), int(c)) for p, c in re.findall(r'CPU-lane picks (\d+), cold (\d+)', txt)]
    cold = {c: [0, 0] for c in configs}
    for k, c in enumerate(order):   # report k is printed when request k starts, about request k-1
        if c is not None and k + 1 < len(reports):
            cold[c][0] += reports[k + 1][0]
            cold[c][1] += reports[k + 1][1]
    base = {r['q']: r['text'] for r in runs[configs[0]]}
    print('\nwarm  vram  sticky   tok/s   right   agree-with-first   SSD-bound picks')
    rows = []
    for c in configs:
        rs = runs[c]
        toks, secs = sum(r['tokens'] for r in rs), sum(r['secs'] for r in rs)
        p, cc = cold[c]
        row = dict(config=c, tps=toks / secs if secs else 0, right=sum(r['right'] for r in rs), n=len(rs),
                   agree=sum(agree(r['text'], base[r['q']]) for r in rs) / max(1, len(rs)), cold=cc / p if p else None)
        rows.append(row)
        cs = f"{100 * row['cold']:.1f}%" if row['cold'] is not None else '-'
        print(f"{c[0]:<5} {c[1]:<5} {c[2]:<7} {row['tps']:6.2f}  {row['right']}/{row['n']}     {row['agree']:.2f}               {cs}")
    res = out / f'results-{stamp}.json'
    res.write_text(json.dumps(dict(rows=rows, runs={str(k): v for k, v in runs.items()}), indent=1), encoding='utf-8')
    print(f'\nSaved {res}. Note: a question\'s first run is slower (later runs find its experts warm); the rotation spreads that.')


if __name__ == '__main__':
    sys.exit(main())
