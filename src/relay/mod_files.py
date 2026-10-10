"""Read mod names from JAR metadata without loading or executing the mod."""
import hashlib
import json
from pathlib import Path
import tomllib
import zipfile

MAX_METADATA = 2 * 1024 * 1024


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def mod_path(directory, relative):
    root = Path(directory).resolve()
    # Managed files are directly under mods/, never arbitrary paths or links.
    parts = relative.split('/')
    if len(parts) != 2 or parts[0] != 'mods' or any(c in parts[1] for c in '\\:'):
        raise ValueError('Invalid mod path')
    if not parts[1].lower().endswith(('.jar', '.jar.disabled')):
        raise ValueError('Only JAR mod files can be managed')
    folder, path = root / 'mods', root / relative
    if any(p.is_symlink() or p.is_junction() for p in (folder, path)):
        raise ValueError('Linked mod folders/files cannot be managed')
    if path.resolve().parent != folder or (path.exists() and not path.is_file()):
        raise ValueError('Invalid mod file')
    return path


def read_mod(path):
    path = Path(path)
    result = dict(filename=path.name, name=path.name, version='Unknown', mod_id='',
                  loader='Unknown', environment='*', enabled=path.name.lower().endswith('.jar'),
                  error=None)
    try:
        with zipfile.ZipFile(path) as jar:
            def read(name):
                info = jar.getinfo(name)
                if info.file_size > MAX_METADATA:
                    raise ValueError('Mod metadata is too large')
                return jar.read(info).decode('utf-8-sig')
            names = jar.namelist()
            if 'fabric.mod.json' in names:
                data = json.loads(read('fabric.mod.json'))
                result.update(name=data.get('name') or data['id'], mod_id=data['id'],
                              version=data['version'], environment=data.get('environment', '*'), loader='Fabric')
            elif 'quilt.mod.json' in names:
                data = json.loads(read('quilt.mod.json'))['quilt_loader']
                result.update(name=data.get('metadata', {}).get('name') or data['id'],
                              mod_id=data['id'], version=data['version'], loader='Quilt')
            else:
                for name, loader in [('META-INF/neoforge.mods.toml', 'NeoForge'), ('META-INF/mods.toml', 'Forge')]:
                    if name in names:
                        data = tomllib.loads(read(name))['mods'][0]
                        result.update(name=data.get('displayName') or data['modId'],
                                      mod_id=data['modId'], version=data.get('version', 'Unknown'), loader=loader)
                        break
            for key in ('name', 'mod_id', 'version', 'environment'):
                if not isinstance(result[key], str):
                    raise ValueError('Invalid ' + key + ' in mod metadata')
                result[key] = result[key].replace('\n', ' ').replace('\r', ' ')[:300]
    except (OSError, ValueError, KeyError, IndexError, TypeError, zipfile.BadZipFile, RuntimeError) as error:
        result['error'] = str(error)
    return result


def scan_mods(directory):
    folder = Path(directory) / 'mods'
    if folder.is_symlink() or folder.is_junction():
        raise ValueError('Linked mod folders cannot be managed')
    if not folder.exists():
        return []
    result = []
    for path in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if path.name.lower().endswith(('.jar', '.jar.disabled')):
            mod_path(directory, 'mods/' + path.name)
            result.append(read_mod(path))
    return result
