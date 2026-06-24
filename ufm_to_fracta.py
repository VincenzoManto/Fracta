"""
ufm_to_fracta.py — UltraFractal .ufm formula converter to Fracta DSL

Converts UltraFractal formula files (.ufm) to equivalent Fracta PIXEL scripts.
Unsupported features are reported as warnings rather than silently dropped.

CLI:
    python ufm_to_fracta.py input.ufm [--out-dir ./output] [--to-oef]

Python API:
    from ufm_to_fracta import UFMConverter
    results = UFMConverter().convert_file("mandelbrot.ufm")
    for r in results:
        print(r.fracta_script)
        for w in r.warnings: print(f"[WARN] {w}")
"""

import re
import sys
import os
import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class UFMBlock:
    name: str
    init_lines: list[str]  = field(default_factory=list)
    loop_lines: list[str]  = field(default_factory=list)
    bailout_lines: list[str] = field(default_factory=list)
    default_vals: dict     = field(default_factory=dict)


@dataclass
class ConversionResult:
    name: str
    fracta_script: str
    warnings: list[str]  = field(default_factory=list)
    ok: bool = True


# ── UFMParser ─────────────────────────────────────────────────────────────────

class UFMParser:
    """Tokenise a .ufm file into UFMBlock objects."""

    _SECTION_RE = re.compile(r'^(init|loop|bailout|default)\s*:', re.IGNORECASE)
    _PARAM_START = re.compile(r'^\s*param\s+\w+', re.IGNORECASE)
    _PARAM_END   = re.compile(r'^\s*endparam\b', re.IGNORECASE)

    def parse_file(self, path: str) -> list[UFMBlock]:
        text = Path(path).read_text(encoding='utf-8', errors='replace')
        return self.parse_text(text)

    def parse_text(self, text: str) -> list[UFMBlock]:
        blocks = []
        # Split on top-level { } pairs
        depth = 0
        start_name = None
        brace_start = 0

        for i, ch in enumerate(text):
            if ch == '{':
                if depth == 0:
                    # name is the identifier on the line before {
                    preceding = text[:i].rstrip()
                    name_line = preceding.rsplit('\n', 1)[-1].strip()
                    # strip inline comments
                    name_line = name_line.split(';')[0].strip()
                    start_name = name_line or 'UnknownFormula'
                    brace_start = i + 1
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and start_name is not None:
                    body = text[brace_start:i]
                    block = self._parse_block(start_name, body)
                    if block:
                        blocks.append(block)
                    start_name = None
        return blocks

    def _parse_block(self, name: str, body: str) -> Optional[UFMBlock]:
        block = UFMBlock(name=name)
        current_section = None
        in_param = False

        for raw_line in body.split('\n'):
            line = raw_line.strip()

            # Skip comments and blanks
            if not line or line.startswith(';'):
                continue

            # Strip inline comments
            if ';' in line:
                line = line[:line.index(';')].strip()
            if not line:
                continue

            # param / endparam blocks — skip entirely
            if self._PARAM_START.match(line):
                in_param = True
                continue
            if self._PARAM_END.match(line):
                in_param = False
                continue
            if in_param:
                continue

            # Section header
            m = self._SECTION_RE.match(line)
            if m:
                current_section = m.group(1).lower()
                continue

            if current_section == 'init':
                block.init_lines.append(line)
            elif current_section == 'loop':
                block.loop_lines.append(line)
            elif current_section == 'bailout':
                block.bailout_lines.append(line)
            elif current_section == 'default':
                # key = value
                if '=' in line:
                    k, _, v = line.partition('=')
                    block.default_vals[k.strip().lower()] = v.strip()
            else:
                # Before any section — treat as global default-like
                if '=' in line:
                    k, _, v = line.partition('=')
                    block.default_vals[k.strip().lower()] = v.strip()

        return block


# ── ExpressionTranslator ──────────────────────────────────────────────────────

class ExpressionTranslator:
    """
    Convert a UltraFractal expression string to a Python/NumPy expression.

    Substitution order matters — more specific patterns go first.
    """

    # (pattern, replacement) — applied in order via re.sub
    _SUBS = [
        # Variables / constants (before function names to avoid partial matches)
        (r'#pixel\b',          'c'),
        (r'#z\b',              'z'),
        (r'#pi\b',             'np.pi'),
        (r'#e\b',              'np.e'),
        (r'#i\b',              '1j'),
        (r'#maxiter\b',        'MAXITER'),   # flagged later

        # Operators
        (r'\^',                '**'),

        # Two-arg functions that need np prefix
        (r'\batan2\s*\(',      'np.arctan2('),

        # sqr(x) in UF means x^2, NOT sqrt.  Handled separately (see _translate_sqr).
        # sqrt goes first so 'sqrt' is not confused with 'sqr'
        (r'\bsqrt\s*\(',       'np.sqrt('),
        # sqr placeholder — will be processed by _translate_sqr after this pass

        # Standard math functions
        (r'\bsinh\s*\(',       'np.sinh('),
        (r'\bcosh\s*\(',       'np.cosh('),
        (r'\btanh\s*\(',       'np.tanh('),
        (r'\basin\s*\(',       'np.arcsin('),
        (r'\bacos\s*\(',       'np.arccos('),
        (r'\batan\s*\(',       'np.arctan('),
        (r'\bsin\s*\(',        'np.sin('),
        (r'\bcos\s*\(',        'np.cos('),
        (r'\btan\s*\(',        'np.tan('),
        (r'\bexp\s*\(',        'np.exp('),
        (r'\blog\s*\(',        'np.log('),
        (r'\babs\s*\(',        'np.abs('),
        (r'\bconj\s*\(',       'np.conj('),
        (r'\breal\s*\(',       'np.real('),
        (r'\bimag\s*\(',       'np.imag('),
        # flip(z) handled separately — wraps as (1j*np.conj(...))
        (r'\btrunc\s*\(',      'np.trunc('),
        (r'\bround\s*\(',      'np.round('),
        (r'\bfloor\s*\(',      'np.floor('),
        (r'\bceil\s*\(',       'np.ceil('),
        (r'\bpow\s*\(',        'np.power('),

        # Complex literal (re, im) → (re + im*1j)
        # Matches patterns like (-0.5, 0.3) or (1/2) in UF center notation
        # Only match if it looks like two numbers
    ]

    # Formula context: comma separator only (slash = division)
    _COMPLEX_LIT = re.compile(
        r'\(\s*(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)\s*,\s*(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)\s*\)'
    )
    # Init/default context: accept both comma and slash (UF uses slash as separator)
    _COMPLEX_LIT_CVAL = re.compile(
        r'\(\s*(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)\s*[,/]\s*(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)\s*\)'
    )

    def translate_cval(self, expr: str) -> tuple[str, list[str]]:
        """Translate a UF constant expression for use as Fracta C_VAL.
        Fracta passes C_VAL into Python's complex() which requires 're+imj' form.
        Accepts both (re, im) and UF slash notation (re/im).
        """
        warnings = []
        e = expr.strip()
        # UF complex literal (re, im) or (re/im) → re+imj
        m = self._COMPLEX_LIT_CVAL.fullmatch(e)
        if m:
            re_part, im_part = m.group(1), m.group(2)
            sign = '+' if not im_part.startswith('-') else ''
            return f'{re_part}{sign}{im_part}j', warnings
        # Fall back to generic translation (may not parse cleanly in complex())
        translated, w = self.translate(e)
        warnings.extend(w)
        warnings.append(
            f"C_VAL '{e}' is not a plain literal — "
            "Fracta's complex() parser may reject it; verify manually"
        )
        return translated, warnings

    def translate(self, expr: str) -> tuple[str, list[str]]:
        """Return (numpy_expr, warnings)."""
        warnings = []
        e = expr

        # Replace complex literals (re, im) → re+im*1j
        e = self._COMPLEX_LIT.sub(lambda m: f'({m.group(1)}+{m.group(2)}*1j)', e)

        # Apply sequential substitutions
        for pat, repl in self._SUBS:
            e = re.sub(pat, repl, e)

        # Handle sqr(expr) → (expr)**2
        e, sqr_warns = self._translate_sqr(e)
        warnings.extend(sqr_warns)

        # Handle flip(expr) → (1j*np.conj(expr))
        e, flip_warns = self._translate_flip(e)
        warnings.extend(flip_warns)

        # Handle |expr| modulus notation
        e, abs_warns = self._translate_pipe_abs(e)
        warnings.extend(abs_warns)

        # Handle UF boolean operators in case they leaked through
        e = e.replace(' && ', ' & ').replace(' || ', ' | ')

        # Flag remaining unsupported tokens
        if 'MAXITER' in e:
            warnings.append("#maxiter is not available as a formula variable in Fracta")
        remaining_hash = re.findall(r'#\w+', e)
        for tok in remaining_hash:
            warnings.append(f"Unsupported UF token '{tok}' — no Fracta equivalent")

        return e, warnings

    def _translate_sqr(self, e: str) -> tuple[str, list[str]]:
        """Replace sqr(expr) with (expr)**2 using parenthesis matching."""
        result = []
        warnings = []
        i = 0
        while i < len(e):
            m = re.search(r'\bsqr\s*\(', e[i:])
            if not m:
                result.append(e[i:])
                break
            result.append(e[i: i + m.start()])
            i += m.end()
            # Find matching closing paren
            depth = 1
            j = i
            while j < len(e) and depth:
                if e[j] == '(':
                    depth += 1
                elif e[j] == ')':
                    depth -= 1
                j += 1
            inner = e[i: j - 1]
            result.append(f'({inner})**2')
            i = j
        return ''.join(result), warnings

    def _translate_flip(self, e: str) -> tuple[str, list[str]]:
        """Replace flip(expr) with (1j*np.conj(expr)).
        In UF, flip(z) swaps real/imaginary parts: flip(a+bi) = b+ai = 1j*conj(a+bi).
        """
        result = []
        warnings = []
        i = 0
        while i < len(e):
            m = re.search(r'\bflip\s*\(', e[i:])
            if not m:
                result.append(e[i:])
                break
            result.append(e[i: i + m.start()])
            i += m.end()
            depth = 1
            j = i
            while j < len(e) and depth:
                if e[j] == '(':
                    depth += 1
                elif e[j] == ')':
                    depth -= 1
                j += 1
            inner = e[i: j - 1]
            result.append(f'(1j*np.conj({inner}))')
            i = j
        return ''.join(result), warnings

    def _translate_pipe_abs(self, e: str) -> tuple[str, list[str]]:
        """Replace |expr| with np.abs(expr) using a simple stack approach."""
        warnings = []
        result = []
        i = 0
        pipe_positions = []  # stack of opening-pipe positions in result

        while i < len(e):
            ch = e[i]
            if ch == '|':
                if pipe_positions:
                    # Closing pipe — pop and wrap
                    open_idx = pipe_positions.pop()
                    inner = ''.join(result[open_idx:])
                    result = result[:open_idx]
                    result.append(f'np.abs({inner})')
                else:
                    # Opening pipe
                    pipe_positions.append(len(result))
            else:
                result.append(ch)
            i += 1

        if pipe_positions:
            # Unmatched pipes — leave as-is
            warnings.append("Unmatched '|' in expression — could not convert modulus notation")

        return ''.join(result), warnings


# Names that are valid inside Fracta's eval() context


# ── CoordMapper ───────────────────────────────────────────────────────────────

class CoordMapper:
    """Convert UF center + magnification to Fracta X_RANGE / Y_RANGE."""

    # UF standard viewport: 3.5 wide × 2.0 tall at magn=1
    _DEFAULT_HALF_W = 1.75
    _DEFAULT_HALF_H = 1.0

    def compute_ranges(self, default_vals: dict) -> tuple[str, str]:
        cx, cy = self._parse_center(default_vals.get('center', ''))
        magn = float(default_vals.get('magn', '1.0') or '1.0')
        if magn <= 0:
            magn = 1.0

        half_w = self._DEFAULT_HALF_W / magn
        half_h = self._DEFAULT_HALF_H / magn

        x_range = f'{cx - half_w:.6g} {cx + half_w:.6g}'
        y_range = f'{cy - half_h:.6g} {cy + half_h:.6g}'
        return x_range, y_range

    def _parse_center(self, s: str) -> tuple[float, float]:
        if not s:
            return -0.5, 0.0
        s = s.strip().strip('()')
        # UF uses '/' as separator: (re/im) or (re, im)
        sep = '/' if '/' in s else ','
        parts = s.split(sep)
        if len(parts) == 2:
            try:
                return float(parts[0].strip()), float(parts[1].strip())
            except ValueError:
                pass
        return -0.5, 0.0


# ── FractaEmitter ─────────────────────────────────────────────────────────────

class FractaEmitter:
    """Produce a Fracta script string from a parsed UFMBlock."""

    _translator = ExpressionTranslator()
    _coord_mapper = CoordMapper()

    def emit(self, block: UFMBlock) -> ConversionResult:
        warnings = []

        # ── Detect Mandelbrot vs Julia mode ──
        mode, julia_c, init_warns = self._detect_mode(block.init_lines)
        warnings.extend(init_warns)

        # ── Extract PARAMs from init (non-z/c constant assignments) ──
        named_params = {}  # name → translated value string
        for line in block.init_lines:
            if not line or '=' not in line:
                continue
            if re.match(r'\s*[zc]\s*=', line, re.IGNORECASE):
                continue
            name, _, val = line.partition('=')
            name = name.strip()
            if not re.fullmatch(r'[A-Za-z_]\w*', name):
                continue
            translated, w = self._translator.translate_cval(val.strip())
            if not w:
                named_params[name] = translated
            else:
                warnings.extend(w)

        # ── Extract STEPs and FORMULA from loop ──
        steps = []       # list of translated assignment strings (lhs = rhs)
        formula_rhs = None
        for line in block.loop_lines:
            if not line or '=' not in line:
                continue
            if re.match(r'\s*z\s*=', line, re.IGNORECASE):
                formula_rhs = line.split('=', 1)[1].strip()
            else:
                lhs, _, rhs = line.partition('=')
                lhs = lhs.strip()
                if not re.fullmatch(r'[A-Za-z_]\w*', lhs):
                    continue
                # Translate RHS; bare "z" → "z.copy()" to capture snapshot
                rhs_tr = rhs.strip()
                if re.fullmatch(r'\s*z\s*', rhs_tr):
                    rhs_tr = 'z.copy()'
                else:
                    rhs_tr, w = self._translator.translate(rhs_tr)
                    warnings.extend(w)
                steps.append(f'{lhs} = {rhs_tr}')

        if formula_rhs is None:
            return ConversionResult(
                name=block.name, fracta_script='',
                warnings=warnings + ['No z = ... assignment found in loop section'],
                ok=False
            )

        np_formula, trans_warns = self._translator.translate(formula_rhs)
        warnings.extend(trans_warns)

        # ── BAILOUT (translate and emit if non-default) ──
        bailout_line = None
        if block.bailout_lines:
            bail_raw = ' '.join(block.bailout_lines).strip()
            bail_tr, bw = self._translator.translate(bail_raw)
            warnings.extend(bw)
            # Default bailout is np.abs(z) <= 2; always emit the translated one
            # so the formula runs with the correct escape radius
            bailout_line = bail_tr

        # ── Coordinates ──
        x_range, y_range = self._coord_mapper.compute_ranges(block.default_vals)

        # ── ITER / COLORMAP ──
        iter_val = block.default_vals.get('maxiter', '100')
        try:
            int(iter_val)
        except (ValueError, TypeError):
            iter_val = '100'
        colormap = block.default_vals.get('colormap', 'magma') or 'magma'

        # ── Assemble Fracta script ──
        out = [f'# Converted from UF: {block.name}', 'ENGINE PIXEL']
        for name, val in named_params.items():
            out.append(f'PARAM {name} {val}')
        for step in steps:
            out.append(f'STEP {step}')
        out.append(f'FORMULA {np_formula}')
        if mode == 'julia' and julia_c:
            out.append(f'C_VAL {julia_c}')
        if bailout_line:
            out.append(f'BAILOUT {bailout_line}')
        out += [f'X_RANGE {x_range}', f'Y_RANGE {y_range}',
                'RES 800', f'ITER {iter_val}', f'COLORMAP {colormap}', 'RENDER']

        return ConversionResult(
            name=block.name,
            fracta_script='\n'.join(out),
            warnings=warnings,
            ok=True
        )

    def _detect_mode(self, init_lines: list[str]) -> tuple[str, Optional[str], list[str]]:
        """Return ('mandelbrot'|'julia', julia_c_string, warnings)."""
        warnings = []
        if not init_lines:
            return 'mandelbrot', None, warnings

        z_init = None
        c_const = None

        for line in init_lines:
            line_low = line.lower().replace(' ', '')
            if line_low.startswith('z='):
                z_init = line.split('=', 1)[1].strip()
            elif line_low.startswith('c='):
                c_const = line.split('=', 1)[1].strip()

        if z_init is None or re.fullmatch(r'0(\.0*)?', z_init or ''):
            return 'mandelbrot', None, warnings

        if '#pixel' in (z_init or '').lower():
            if c_const:
                # Julia: translate c constant for C_VAL (needs re+imj form)
                julia_c, w = ExpressionTranslator().translate_cval(c_const)
                warnings.extend(w)
                return 'julia', julia_c, warnings
            else:
                return 'julia', None, warnings

        warnings.append(
            f"Non-trivial init 'z = {z_init}' not supported — defaulting to Mandelbrot mode"
        )
        return 'mandelbrot', None, warnings



# ── UFMConverter (top-level) ──────────────────────────────────────────────────

class UFMConverter:
    """Orchestrates parse → translate → emit for one or more .ufm files."""

    _parser  = UFMParser()
    _emitter = FractaEmitter()

    def convert_file(self, path: str) -> list[ConversionResult]:
        blocks = self._parser.parse_file(path)
        if not blocks:
            return [ConversionResult(
                name=Path(path).stem,
                fracta_script='',
                warnings=['No formula blocks found in file'],
                ok=False
            )]
        return [self._emitter.emit(b) for b in blocks]

    def convert_text(self, text: str) -> list[ConversionResult]:
        blocks = self._parser.parse_text(text)
        return [self._emitter.emit(b) for b in blocks]


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_result(r: ConversionResult, verbose: bool = True) -> None:
    status = 'OK' if r.ok else 'SKIP'
    print(f'\n{"-"*60}')
    print(f'[{status}] {r.name}')
    if r.fracta_script:
        print()
        print(r.fracta_script)
    if r.warnings and verbose:
        print()
        for w in r.warnings:
            print(f'  [WARN] {w}')


def main():
    ap = argparse.ArgumentParser(
        description='Convert UltraFractal .ufm formula files to Fracta scripts'
    )
    ap.add_argument('input', help='Path to .ufm file')
    ap.add_argument('--out-dir', metavar='DIR',
                    help='Write one .fracta file per formula into this directory')
    ap.add_argument('--to-oef', action='store_true',
                    help='Import successful conversions into the OEF database (requires code.py)')
    ap.add_argument('--quiet', action='store_true',
                    help='Suppress per-formula warnings')
    args = ap.parse_args()

    converter = UFMConverter()
    results = converter.convert_file(args.input)

    ok_count = sum(1 for r in results if r.ok)
    print(f'Parsed {len(results)} formula(s) — {ok_count} convertible.')

    if args.out_dir:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

    oef_db = None
    if args.to_oef:
        try:
            import importlib.util, types
            spec = importlib.util.spec_from_file_location(
                'code', Path(__file__).parent / 'code.py')
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            oef_db = mod.db
        except Exception as ex:
            print(f'[ERROR] Could not load OEFDatabase from code.py: {ex}')

    for r in results:
        _print_result(r, verbose=not args.quiet)

        if r.ok and args.out_dir:
            safe_name = re.sub(r'[^\w\-]', '_', r.name)
            out_path = Path(args.out_dir) / f'{safe_name}.fracta'
            out_path.write_text(r.fracta_script, encoding='utf-8')
            print(f'  -> Written to {out_path}')

        if r.ok and oef_db is not None:
            try:
                oef_db.submit(
                    name=f'[UF] {r.name}',
                    script_text=r.fracta_script,
                    comments=f'Converted from UltraFractal formula: {r.name}',
                    keywords=['PIXEL', 'uf-import']
                )
                print(f'  -> Submitted to OEF database')
            except Exception as ex:
                print(f'  [ERROR] OEF submission failed: {ex}')

    print(f'\nDone. {ok_count}/{len(results)} formulas converted.')


if __name__ == '__main__':
    main()
