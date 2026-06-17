import matplotlib.pyplot as plt
import numpy as np
import random

class Fracta:
    def __init__(self):
        self.reset()
        
    def reset(self):
        self.engine = None
        self.params = {}
        self.rules = []

    def run(self, script_text):
        self.reset()
        lines = script_text.strip().split('\n')
        
        render_mode = 'VECTOR'
        for line in lines:
            if line.strip().upper() == 'RENDER_AS_GRID':
                render_mode = 'GRID'
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
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
        else:
            print(f"Error: unknown '{self.engine}' engine.")

    def _parse_angle(self, raw):
        raw = str(raw).strip()
        if raw.endswith('r'):
            return float(raw[:-1]) * (180.0 / np.pi)
        return float(raw)

    def _render_l_system(self):
        rules_dict = {}
        for r in self.rules:
            left, right = r.split('->')
            rules_dict[left.strip()] = right.strip()
            
        axiom = self.params.get('AXIOM', '')
        iterations = int(self.params.get('ITER', '1'))
        angle = self._parse_angle(self.params.get('ANGLE', '0'))
        
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
        rules_dict = {}
        for r in self.rules:
            if '->' not in r:
                continue
                
            parts = r.split('->')
            if len(parts) >= 2:
                left = parts[0].strip()
                right = parts[-1].strip() 
                rules_dict[left] = right
            
        axiom = self.params.get('AXIOM', '')
        iterations = int(self.params.get('ITER', '1'))
        cmap = self.params.get('COLORMAP', 'binary')
        
        current = axiom
        grid_history = []
        
        for _ in range(iterations):
            row = [1 if char == '1' else 0 for char in current]
            grid_history.append(row)
            
            next_string = []
            for i in range(len(current)):
                center = current[i]
                right = current[i+1] if i < len(current) - 1 else '|'
                
                key_with_context = f"{center} > {right}"
                key_fallback = f"{center} > 0" if right == '|' else None
                
                if key_with_context in rules_dict:
                    next_string.append(rules_dict[key_with_context])
                elif key_fallback and key_fallback in rules_dict:
                    next_string.append(rules_dict[key_fallback])
                else:
                    next_string.append(center)
                    
            current = "".join(next_string)
            
        if not grid_history:
            return

        matrix = np.array(grid_history, dtype=float)
        self._plot_builder(matrix, None, style='grid', cmap=cmap)

    def _render_pixel(self):
        xmin, xmax = map(float, self.params.get('X_RANGE', '-2.0 2.0').split())
        ymin, ymax = map(float, self.params.get('Y_RANGE', '-2.0 2.0').split())
        res = int(self.params.get('RES', '500'))
        iterations = int(self.params.get('ITER', '100'))
        formula = self.params.get('FORMULA', 'z**2 + c')
        cmap = self.params.get('COLORMAP', 'twilight_shifted')
        
        x = np.linspace(xmin, xmax, res)
        y = np.linspace(ymin, ymax, res)
        X, Y = np.meshgrid(x, y)
        grid = X + 1j * Y
        
        if 'C_VAL' in self.params:
            c = complex(self.params['C_VAL'].replace(' ', ''))
            z = grid
        else:
            c = grid
            z = np.zeros_like(c)
            
        img = np.zeros(z.shape, dtype=float)
        
        for i in range(iterations):
            mask = np.abs(z) <= 2.0
            z[mask] = eval(formula, {"z": z[mask], "c": c[mask], "np": np})
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

    def _plot_builder(self, data_x, data_y, style='line', cmap='inferno'):
        plt.figure(figsize=(10, 10))
        ax = plt.gca()
        
        if style == 'grid':
            ax.set_facecolor('#e9e9e9')
            plt.gcf().patch.set_facecolor('#ffffff')
            
            plt.imshow(data_x, cmap='binary', interpolation='nearest', origin='upper', alpha=0.15)
            
            rows, cols = data_x.shape
            for r in range(rows):
                for c in range(cols):
                    val = int(data_x[r, c])
                    font_weight = 'bold' if val == 1 else 'normal'
                    color = '#000000' if val == 1 else '#444444'
                    
                    ax.text(c, r, str(val), va='center', ha='center', 
                            fontsize=9, weight=font_weight, color=color)
            
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
        elif style == 'scatter':
            plt.scatter(data_x, data_y, s=0.1, color='#33ff33', alpha=0.6)
            plt.axis('equal')
            
        plt.axis('off')
        plt.tight_layout()
        plt.show()

f_pro = Fracta()

koch_snowflake = """
ENGINE L_SYSTEM
AXIOM F--F--F
RULE F -> F+F--F+F
ANGLE 60
ITER 4
RENDER
"""

f_pro.run(koch_snowflake)
pianta = """
ENGINE L_SYSTEM
AXIOM X
RULE X -> F+[[X]-X]-F[-FX]+X
RULE F -> FF
ANGLE 25
ITER 5
RENDER
"""
f_pro.run(pianta)
mandelbrot_custom = """
ENGINE PIXEL
FORMULA np.conj(z)**2 + c
X_RANGE -2.0 1.5
Y_RANGE -1.5 1.5
RES 600
ITER 60
COLORMAP magma
RENDER
"""
f_pro.run(mandelbrot_custom)
felce = """
ENGINE IFS
ITER 80000
# Regole: prob, a, b, c, d, e, f
RULE 0.01   0.0   0.0   0.0   0.16  0.0  0.0
RULE 0.85   0.85  0.04 -0.04  0.85  0.0  1.6
RULE 0.07   0.2  -0.26  0.23  0.22  0.0  1.6
RULE 0.07  -0.15  0.28  0.26  0.24  0.0  0.44
RENDER
"""
f_pro.run(felce)


f_pro.run(rule6_excel_style)
