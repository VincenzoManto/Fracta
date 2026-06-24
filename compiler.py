import matplotlib.pyplot as plt
import numpy as np
import random

class FractaPro:
    def __init__(self):
        self.reset()
        
    def reset(self):
        self.engine = None
        self.params = {}
        self.rules = []
        self.steps = []       # STEP directives for PIXEL engine (ordered)
        self.param_defs = []  # PARAM directives: "name value"

    def run(self, script_text):
        self.reset()
        lines = script_text.strip().split('\n')

        # Scansione preventiva per determinare la modalità di rendering finale
        render_mode = 'VECTOR'
        for line in lines:
            if line.strip().upper() == 'RENDER_AS_GRID':
                render_mode = 'GRID'

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '#' in line:
                line = line[:line.index('#')].strip()
            if not line:
                continue

            parts = line.split(maxsplit=1)
            cmd = parts[0].upper()

            if cmd == 'ENGINE':
                self.engine = parts[1].upper()
            elif cmd in ['RENDER', 'RENDER_AS_GRID']:
                self._render(render_mode)
            else:
                if len(parts) > 1:
                    val = parts[1]
                    if cmd == 'RULE':
                        self.rules.append(val)
                    elif cmd == 'STEP':
                        self.steps.append(val)
                    elif cmd == 'PARAM':
                        self.param_defs.append(val)
                    else:
                        self.params[cmd] = val

    def _render(self, render_mode):
        if self.engine == 'L_SYSTEM':
            if render_mode == 'GRID':
                self._render_grid()
            else:
                self._render_l_system()
        elif self.engine == 'PIXEL':
            self._render_pixel()
        elif self.engine == 'IFS':
            self._render_ifs()
        elif self.engine == 'REACTION_DIFFUSION':
            self._render_reaction_diffusion()
        else:
            print(f"Errore: Motore '{self.engine}' sconosciuto.")

    def _render_l_system(self):
        rules_dict = {}
        for r in self.rules:
            left, right = r.split('->')
            rules_dict[left.strip()] = right.strip()
            
        axiom = self.params.get('AXIOM', '')
        iterations = int(self.params.get('ITER', '1'))
        angle = float(self.params.get('ANGLE', '0'))
        
        current = axiom
        for _ in range(iterations):
            current = "".join([rules_dict.get(c, c) for c in current])
            
        x, y = 0.0, 0.0
        current_angle = 90.0
        x_pts, y_pts = [x], [y]
        stack = []
        
        for char in current:
            if char in ['F', 'G']:
                x += np.cos(np.radians(current_angle))
                y += np.sin(np.radians(current_angle))
                x_pts.append(x)
                y_pts.append(y)
            elif char == 'f':
                x += np.cos(np.radians(current_angle))
                y += np.sin(np.radians(current_angle))
                x_pts.extend([None, x])
                y_pts.extend([None, y])
            elif char == '+': current_angle += angle
            elif char == '-': current_angle -= angle
            elif char == '[': stack.append((x, y, current_angle))
            elif char == ']':
                x, y, current_angle = stack.pop()
                x_pts.extend([None, x])
                y_pts.extend([None, y])

        self._plot_builder(x_pts, y_pts, style='line')

    def _render_grid(self):
        """Engine di Rendering Matriziale con supporto al contesto destro (Excel 2-Squares)."""
        rules_dict = {}
        for r in self.rules:
            # Protezione: saltiamo la riga se non contiene il separatore corretto
            if '->' not in r:
                continue
                
            parts = r.split('->')
            # Se ci sono strani sdoppiamenti, prendiamo solo il primo e l'ultimo elemento valido
            if len(parts) >= 2:
                left = parts[0].strip()
                right = parts[-1].strip() # Prende l'output finale isolando eventuali code
                rules_dict[left] = right
            
        axiom = self.params.get('AXIOM', '')
        # ... (tutto il resto del codice di _render_grid rimane identico) ...
        iterations = int(self.params.get('ITER', '1'))
        cmap = self.params.get('COLORMAP', 'binary')
        
        current = axiom
        grid_history = []
        
        for _ in range(iterations):
            # Salva la riga corrente nella storia della griglia (1 = Nero, 0 = Bianco)
            row = [1 if char == '1' else 0 for char in current]
            grid_history.append(row)
            
            next_string = []
            # Scansione della stringa con analisi del contesto destro
            for i in range(len(current)):
                center = current[i]
                # Se siamo alla fine della stringa, il contesto destro è il bordo '|'
                right = current[i+1] if i < len(current) - 1 else '|'
                
                # Cerca prima la regola con il contesto esplicito (es. "0 > 1")
                key_with_context = f"{center} > {right}"
                # Se non trova il contesto specifico del bordo, applica la lettura di Excel (bordo = 0)
                key_fallback = f"{center} > 0" if right == '|' else None
                
                if key_with_context in rules_dict:
                    next_string.append(rules_dict[key_with_context])
                elif key_fallback and key_fallback in rules_dict:
                    next_string.append(rules_dict[key_fallback])
                else:
                    # Se non c'è nessuna regola di contesto, mantiene lo stato precedente
                    next_string.append(center)
                    
            current = "".join(next_string)
            
        if not grid_history:
            return

        # Costruzione della matrice finale
        matrix = np.array(grid_history, dtype=float)
        self._plot_builder(matrix, None, style='grid', cmap=cmap)

    def _render_pixel(self):
        xmin, xmax = map(float, self.params.get('X_RANGE', '-2.0 2.0').split())
        ymin, ymax = map(float, self.params.get('Y_RANGE', '-2.0 2.0').split())
        res = int(self.params.get('RES', '500'))
        iterations = int(self.params.get('ITER', '100'))
        formula = self.params.get('FORMULA', 'z**2 + c')
        cmap = self.params.get('COLORMAP', 'twilight_shifted')
        bailout_expr = self.params.get('BAILOUT', None)

        # Parse PARAM directives: each entry is "name value"
        named_params = {}
        for p_def in self.param_defs:
            parts = p_def.split(None, 1)
            if len(parts) == 2:
                name, val = parts
                try:
                    named_params[name] = complex(val.replace(' ', ''))
                except ValueError:
                    try:
                        named_params[name] = float(val)
                    except ValueError:
                        pass

        x = np.linspace(xmin, xmax, res)
        y = np.linspace(ymin, ymax, res)
        X, Y = np.meshgrid(x, y)
        grid = X + 1j * Y

        if 'C_VAL' in self.params:
            c = complex(self.params['C_VAL'].replace(' ', ''))
            z = grid.copy()
        else:
            c = grid.copy()
            z = np.zeros_like(c)

        img = np.zeros(z.shape, dtype=float)
        grid_shape = z.shape

        def _mask_ctx(full, step_vars, mask):
            """Slice all grid-shaped numpy arrays to mask; leave scalars/params intact."""
            ctx = {}
            combined = {**full, **step_vars}
            for k, v in combined.items():
                if isinstance(v, np.ndarray) and v.shape == grid_shape:
                    ctx[k] = v[mask]
                else:
                    ctx[k] = v
            return ctx

        for _ in range(iterations):
            # Full-grid context (STEPs see the complete arrays)
            full_ctx = {'z': z, 'c': c, 'np': np, **named_params}

            # Execute STEP directives in order on the full grid
            step_vars = {}
            for step in self.steps:
                if '=' in step:
                    lhs, _, rhs = step.partition('=')
                    step_vars[lhs.strip()] = eval(rhs.strip(), {**full_ctx, **step_vars})

            # Compute escape mask
            if bailout_expr:
                mask = eval(bailout_expr, {**full_ctx, **step_vars})
            else:
                mask = np.abs(z) <= 2.0

            # Evaluate FORMULA only on non-escaped pixels
            masked_ctx = _mask_ctx(full_ctx, step_vars, mask)
            if isinstance(c, complex):
                masked_ctx['c'] = c  # scalar Julia constant, don't slice
            z[mask] = eval(formula, masked_ctx)
            img[mask] += 1

        self._plot_builder(img, None, style='pixel', cmap=cmap)

    def _render_ifs(self):
        iterations = int(self.params.get('ITER', '50000'))
        parsed_rules = []
        for r in self.rules:
            parsed_rules.append(list(map(float, r.split())))
            
        probs = [r[0] for r in parsed_rules]
        probs = np.array(probs) / sum(probs)
        
        x, y = 0.0, 0.0
        x_pts, y_pts = [], []
        
        for _ in range(iterations):
            rule = random.choices(parsed_rules, weights=probs)[0]
            _, a, b, c, d, e, f = rule
            next_x = a * x + b * y + e
            next_y = c * x + d * y + f
            x, y = next_x, next_y
            x_pts.append(x)
            y_pts.append(y)
            
        self._plot_builder(x_pts, y_pts, style='scatter')

    def _render_reaction_diffusion(self):
        res   = int(self.params.get('RES',   '256'))
        steps = int(self.params.get('STEPS', '4000'))
        f     = float(self.params.get('FEED', '0.055'))
        k     = float(self.params.get('KILL', '0.062'))
        Du    = float(self.params.get('DU',   '0.16'))
        Dv    = float(self.params.get('DV',   '0.08'))
        cmap  = self.params.get('COLORMAP', 'RdYlBu')

        u = np.ones((res, res))
        v = np.zeros((res, res))

        # Perturbazione casuale in un quadrato centrale come seme iniziale
        r = max(res // 10, 4)
        cx, cy = res // 2, res // 2
        u[cx-r:cx+r, cy-r:cy+r] = 0.50 + np.random.uniform(-0.01, 0.01, (2*r, 2*r))
        v[cx-r:cx+r, cy-r:cy+r] = 0.25 + np.random.uniform(-0.01, 0.01, (2*r, 2*r))

        def lap(m):
            return (np.roll(m,  1, 0) + np.roll(m, -1, 0) +
                    np.roll(m,  1, 1) + np.roll(m, -1, 1) - 4 * m)

        for _ in range(steps):
            uvv  = u * v * v
            u   += Du * lap(u) - uvv + f * (1 - u)
            v   += Dv * lap(v) + uvv - (f + k) * v
            np.clip(u, 0, 1, out=u)
            np.clip(v, 0, 1, out=v)

        self._plot_builder(v, None, style='heatmap', cmap=cmap)

    def _plot_builder(self, data_x, data_y, style='line', cmap='inferno'):
        plt.figure(figsize=(10, 10))
        ax = plt.gca()
        
        if style == 'grid':
            # Sfondo grigio chiaro per l'area dati, simile al foglio Excel disattivato
            ax.set_facecolor('#e9e9e9')
            plt.gcf().patch.set_facecolor('#ffffff')
            
            # Usiamo una mappa di colori invertita (0 = Bianco, 1 = Nero)
            plt.imshow(data_x, cmap='binary', interpolation='nearest', origin='upper', alpha=0.15)
            
            # Matrice di testo: stampa lo 0 o l'1 in ogni singola coordinata della griglia
            rows, cols = data_x.shape
            for r in range(rows):
                for c in range(cols):
                    val = int(data_x[r, c])
                    # Se il valore è 1 (nero), usa un testo più marcato o un colore coordinato
                    font_weight = 'bold' if val == 1 else 'normal'
                    color = '#000000' if val == 1 else '#444444'
                    
                    ax.text(c, r, str(val), va='center', ha='center', 
                            fontsize=9, weight=font_weight, color=color)
            
            # Impostiamo i limiti corretti per non tagliare i numeri ai bordi
            plt.xlim(-0.5, cols - 0.5)
            plt.ylim(rows - 0.5, -0.5)
            
        elif style == 'line':
            ax.set_facecolor('#0d0d11')
            plt.gcf().patch.set_facecolor('#0d0d11')
            plt.plot(data_x, data_y, color='#00ffcc', linewidth=0.5)
            plt.axis('equal')
        elif style == 'pixel':
            plt.imshow(data_x, cmap=cmap, extent=[-2, 2, -2, 2], origin='lower')
            plt.axis('equal')
        elif style == 'heatmap':
            plt.imshow(data_x, cmap=cmap, origin='lower', interpolation='bilinear')
            plt.axis('equal')
        elif style == 'scatter':
            plt.scatter(data_x, data_y, s=0.1, color='#33ff33', alpha=0.6)
            plt.axis('equal')
            
        plt.axis('off')
        plt.tight_layout()
        plt.show()