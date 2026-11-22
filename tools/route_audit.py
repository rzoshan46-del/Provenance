import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json, re, inspect
from pathlib import Path
from fastapi import FastAPI
from app.main import app

def list_routes():
    routes = []
    for r in app.routes:
        if hasattr(r, 'methods'):
            routes.append({
                'path': r.path,
                'methods': set(r.methods),
                'endpoint': r.endpoint,
                'name': r.name,
            })
    return routes

def parse_handler_params(func):
    sig = inspect.signature(func)
    params = []
    for name, p in sig.parameters.items():
        default = p.default
        if getattr(default, '__class__', None).__name__ == 'Form':
            params.append((name, 'form'))
        elif getattr(default, '__class__', None).__name__ == 'Body':
            params.append((name, 'body'))
        else:
            params.append((name, 'other'))
    return params

def scan_templates():
    tmpl_dir = Path('app/templates')
    links = set()
    forms = []
    for file in tmpl_dir.rglob('*.html'):
        text = file.read_text(encoding='utf-8')
        for m in re.finditer(r'href="([^"]+)"', text):
            link = m.group(1)
            if '{{' not in link:
                links.add(link)
        for m in re.finditer(r'<form[^>]*action="([^"]*)"[^>]*method="([^"]*)"', text, re.I):
            action = m.group(1)
            method = m.group(2).upper()
            if '{{' in action:
                continue
            forms.append({
                'action': action or '/',
                'method': method,
                'file': str(file),
                'inputs': re.findall(r'<input[^>]*name="([^"]+)"', text, re.I),
            })
    return links, forms

def scan_js():
    js_dir = Path('app/static')
    selectors = set()
    for file in js_dir.rglob('*.js'):
        text = file.read_text(encoding='utf-8')
        for m in re.finditer(r'getElementById\([\"\']([^\"\']+)[\"\']\)', text):
            selectors.add('#' + m.group(1))
        for m in re.finditer(r'querySelector\([\"\']([^\"\']+)[\"\']\)', text):
            selectors.add(m.group(1))
    return selectors

def main():
    routes = list_routes()
    route_paths = {r['path'] for r in routes}
    links, forms = scan_templates()
    js_selectors = scan_js()
    issues = []
    # a) URLs with no matching route
    for link in links:
        if link.startswith('/') and link not in route_paths:
            issues.append(('404', link))
    # b) method mismatches for forms
    for f in forms:
        act = f['action'] or '/'
        meth = f['method']
        matching = [r for r in routes if r['path']==act]
        if not matching:
            issues.append(('404_form', act))
        else:
            allowed = set().union(*[r['methods'] for r in matching])
            if meth not in allowed:
                issues.append(('405_form', f"{act} {meth}"))
        # c) field name mismatches
        for r in matching:
            params = parse_handler_params(r['endpoint'])
            form_names = set(f['inputs'])
            expected = {n for n,t in params if t=='form'}
            if not expected.issubset(form_names):
                issues.append(('422_form', f"{act} missing {expected - form_names}"))
    # d) JS selector errors (simple check against ids in templates)
    ids_in_templates = set()
    for file in Path('app/templates').rglob('*.html'):
        txt = file.read_text(encoding='utf-8')
        for m in re.finditer(r'id=[\"\']([^\"\']+)[\"\']', txt):
            ids_in_templates.add('#'+m.group(1))
    for sel in js_selectors:
        if sel.startswith('#') and sel not in ids_in_templates:
            issues.append(('JS_missing', sel))
    # Print compact table
    print('ISSUE\tDETAIL')
    for typ, detail in issues[:60]:
        print(f"{typ}\t{detail}")
    if issues:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == '__main__':
    main()
