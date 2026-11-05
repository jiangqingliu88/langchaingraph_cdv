# src/regression_framework/reporters/html.py
import os
from datetime import datetime
from jinja2 import Template
from ..core.logging_config import get_logger

logger = get_logger(__name__)

class HtmlReporter:
    def generate(self, tasks, root_dir, total_time="N/A"):
        stats = {'pass': 0, 'fail': 0, 'unknown': 0}
        build_groups = {}
        for task in tasks:
            stats[task.status] += 1
            build_key = getattr(task, 'build_name', task.name)
            if build_key not in build_groups:
                build_groups[build_key] = {
                    'pass': 0, 'fail': 0, 'unknown': 0,
                    'total': 0, 'tasks': []
                }
            build_groups[build_key][task.status] += 1
            build_groups[build_key]['total'] += 1
            build_groups[build_key]['tasks'].append(task)

        total = len(tasks)
        pass_rate = (stats['pass'] / total * 100) if total > 0 else 0

        template_str = '''<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Regression Report</title>
<style>
body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
.container { max-width: 1200px; margin: auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
.summary { display: flex; gap: 20px; flex-wrap: wrap; margin: 20px 0; }
.summary-card { background: #f9f9f9; padding: 15px 25px; border-radius: 5px; flex: 1; min-width: 100px; text-align: center; }
.summary-card .number { font-size: 28px; font-weight: bold; }
.pass .number { color: #4CAF50; } .fail .number { color: #f44336; } .unknown .number { color: #ff9800; }
.pass-rate { font-size: 24px; font-weight: bold; color: #2196F3; }
.build-section { margin: 30px 0; border: 1px solid #ddd; border-radius: 5px; }
.build-header { background: #e0e0e0; padding: 10px 15px; cursor: pointer; font-weight: bold; display: flex; justify-content: space-between; }
.build-header:hover { background: #d0d0d0; }
.test-table { width: 100%; border-collapse: collapse; }
.test-table th, .test-table td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #eee; }
.test-table th { background: #f2f2f2; }
.status-badge { padding: 2px 10px; border-radius: 12px; color: white; font-size: 12px; font-weight: bold; }
.status-pass { background: #4CAF50; } .status-fail { background: #f44336; } .status-unknown { background: #ff9800; }
.performance-badge { background: #ff6f00; color: white; padding: 2px 8px; border-radius: 12px; font-size: 10px; }
.wave-link { color: #2196F3; text-decoration: none; }
.wave-link:hover { text-decoration: underline; }
</style>
</head>
<body>
<div class="container">
    <h1>Regression Report</h1>
    <p>Generated: {{ generated }} | Total Time: {{ total_time }}</p>
    <div class="summary">
        <div class="summary-card"><div class="number">{{ total }}</div><div class="label">Total</div></div>
        <div class="summary-card pass"><div class="number">{{ pass }}</div><div class="label">Pass</div></div>
        <div class="summary-card fail"><div class="number">{{ fail }}</div><div class="label">Fail</div></div>
        <div class="summary-card unknown"><div class="number">{{ unknown }}</div><div class="label">Unknown</div></div>
        <div class="summary-card"><div class="pass-rate">{{ pass_rate }}%</div><div class="label">Pass Rate</div></div>
    </div>
    {% for build_name, group in build_groups.items() %}
    <div class="build-section">
        <div class="build-header" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'">
            <span>Build: {{ build_name }}</span>
            <span>Total: {{ group.total }} | Pass: {{ group.pass }} | Fail: {{ group.fail }} | Unknown: {{ group.unknown }}</span>
        </div>
        <div class="build-tests" style="display:block">
            <table class="test-table">
                <thead><tr>
                    <th>Test Name</th>
                    <th>Status</th>
                    <th>Sim Time (s)</th>
                    <th>Waveform</th>
                    <th>Job ID</th>
                    <th>Directory</th>
                </tr></thead>
                <tbody>
                {% for task in group.tasks %}
                <tr>
                    <td>{{ task.name }}{% if task.performance_degraded %} <span class="performance-badge">PERF</span>{% endif %}</td>
                    <td><span class="status-badge status-{{ task.status }}">{{ task.status.upper() }}</span></td>
                    <td>{{ "%.2f"|format(task.sim_time) if task.sim_time else "-" }}</td>
                    <td>{% if task.wave_path %}<a href="{{ task.wave_path }}" class="wave-link" target="_blank">📊 Wave</a>{% else %}-{% endif %}</td>
                    <td>{% if task.job_id %}{{ task.job_id }}{% endif %}</td>
                    <td class="test-dir">{{ task.work_dir }}</td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    {% endfor %}
</div>
</body>
</html>'''

        template = Template(template_str)
        context = {
            'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_time': total_time,
            'total': total,
            'pass': stats['pass'],
            'fail': stats['fail'],
            'unknown': stats['unknown'],
            'pass_rate': f"{pass_rate:.1f}",
            'build_groups': build_groups
        }
        html_path = os.path.join(root_dir, 'report.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(template.render(**context))
        logger.info(f"HTML report: {html_path}")