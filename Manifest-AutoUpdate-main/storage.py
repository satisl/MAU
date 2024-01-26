import os
import vdf
import time
import shutil
import winreg
import argparse
import requests
import traceback
import subprocess
from pathlib import Path
from multiprocessing.pool import ThreadPool
from multiprocessing.dummy import Pool, Lock

lock = Lock()


def get(sha, path):
    url_list = [f'https://ghproxy.com/https://raw.githubusercontent.com/{repo}/{sha}/{path}', f'https://cdn.jsdelivr.net/gh/{repo}@{sha}/{path}', f'https://raw.staticdn.net/{repo}/{sha}/{path}', f'https://raw.fastgit.org/{repo}/{sha}/{path}'
                ]
    retry = 8
    while True:
        for url in url_list:
            try:
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    return r.content
                elif r.status_code == 404:
                    return False
            except:
                print(f'获取失败: {path}')
                retry -= 1
                if not retry:
                    print(f'超过最大重试次数: {path}')
                    raise


def get_manifest(sha, path, steam_path: Path, app_id):
    try:
        if path.endswith('.manifest'):
            depot_cache_path = steam_path / 'depotcache'
            with lock:
                if not depot_cache_path.exists():
                    depot_cache_path.mkdir(exist_ok=True)
            save_path = depot_cache_path / path
            if save_path.exists():
                with lock:
                    print(f'已存在清单: {path}')
                return
            content = get(sha, path)
            with lock:
                print(f'清单下载成功: {path}')
            with save_path.open('wb') as f:
                f.write(content)
        elif path == 'config.vdf':
            content = get(sha, path)
            with lock:
                print(f'密钥下载成功: {path}')
            depots_config = vdf.loads(content.decode(encoding='utf-8'))
            if depotkey_merge(steam_path / 'config' / path, depots_config):
                print('合并config.vdf成功')
            if not args.greenluma and stool_add(
                    [(depot_id, '1', depots_config['depots'][depot_id]['DecryptionKey'])
                     for depot_id in depots_config['depots']], app_id):
                print('导入steamtools成功')
    except KeyboardInterrupt:
        raise
    except:
        traceback.print_exc()
        raise
    return True


def depotkey_merge(config_path, depots_config):
    if not config_path.exists():
        with lock:
            print('config.vdf不存在')
        return
    with open(config_path, encoding='utf-8') as f:
        config = vdf.load(f)
    software = config['InstallConfigStore']['Software']
    valve = software.get('Valve') or software.get('valve')
    steam = valve.get('Steam') or valve.get('steam')
    if 'depots' not in steam:
        steam['depots'] = {}
    steam['depots'].update(depots_config['depots'])
    with open(config_path, 'w', encoding='utf-8') as f:
        vdf.dump(config, f, pretty=True)
    return True


def stool_add(depot_list, app_id):
    steam_path = get_steam_path()
    lua_name = f'{app_id}.lua'
    lua_path = steam_path / 'config' / 'stplug-in' / lua_name
    luapacka_path = steam_path / 'config' / 'stplug-in' / 'luapacka.exe'
    content = f'addappid({app_id}, 1 , nil)'
    for depot_id, type_, depot_key in depot_list:
        content += f'''\naddappid({depot_id}, {type_}, '{depot_key}')'''
    with open(lua_path, 'w', encoding='utf-8') as f:
        f.write(content)
    subprocess.run([str(luapacka_path), str(lua_path)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    os.remove(lua_path)
    return True


def gl_add(app_id, dlc_id, manifest_id):
    try:
        steam_path = get_steam_path()
        applist_path = steam_path / 'AppList'
        id_list = [app_id]
        if dlc_id is not None:
            id_list.extend(dlc_id)
        if manifest_id is not None:
            id_list.extend(manifest_id)
        if not applist_path.exists():
            applist_path.mkdir(exist_ok=True)
        depot_dict = {}
        for i in applist_path.iterdir():
            if i.suffix == '.txt':
                with i.open('r', encoding='utf-8') as f:
                    app_id = f.read().strip()
                    if args.delete:
                        if app_id in id_list:
                            f.close()
                            os.remove(applist_path / i.name)
                            print(f'删除{i.name}')
                    depot_dict[int(i.stem)] = None
                    if app_id.isdecimal():
                        depot_dict[int(i.stem)] = int(app_id)
        if not args.delete:
            for id in id_list:
                if int(id) not in depot_dict.values():
                    index = max(depot_dict.keys()) + \
                        1 if depot_dict.keys() else 0
                    if index != 0:
                        for i in range(max(depot_dict.keys())):
                            if i not in depot_dict.keys():
                                index = i
                    with (applist_path / f'{index}.txt').open('w', encoding='utf-8') as f:
                        f.write(str(id))
                    depot_dict[index] = int(id)
        appcache_path = steam_path / 'appcache'
        if appcache_path.exists():
            shutil.rmtree(appcache_path)
    except:
        traceback.print_exc()
        raise
    print('导入greenluma成功')
    return True


def get_steam_path():
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam')
    steam_path = Path(winreg.QueryValueEx(key, 'SteamPath')[0])
    return steam_path


def get_dlc_id(app_id):
    url = f'https://api.github.com/repos/{repo}/branches/data'
    r = requests.get(url)
    if 'commit' in r.json():
        sha = r.json()['commit']['sha']
        idList = get(sha, 'ids.json')
        idList = {} if idList == False else eval(idList)
        if app_id in idList:
            dlc_id = idList[app_id]['dlcid']
            return dlc_id


def main(app_id):
    url = f'https://api.github.com/repos/{repo}/branches/{app_id}'
    r = requests.get(url)
    if 'commit' in r.json():
        sha = r.json()['commit']['sha']
        url = r.json()['commit']['commit']['tree']['url']
        r = requests.get(url)
        if 'tree' in r.json():
            result_list = []
            manifest_id = []
            with Pool(32) as pool:
                pool: ThreadPool
                for i in r.json()['tree']:
                    if args.greenluma:
                        if i['path'].endswith('.manifest'):
                            id = i['path'].split('_')[0]
                            manifest_id.append(id)
                    if not args.delete:
                        result_list.append(pool.apply_async(
                            get_manifest, (sha, i['path'], get_steam_path(), app_id)))
                if args.greenluma:
                    result_list.append(pool.apply_async(
                        gl_add, (app_id, get_dlc_id(app_id), manifest_id)))
                try:
                    while pool._state == 'RUN':
                        if all([result.ready() for result in result_list]):
                            break
                        time.sleep(0.1)
                except KeyboardInterrupt:
                    with lock:
                        pool.terminate()
                    raise
            if all([result.successful() for result in result_list]):
                print(f'入库成功: {app_id}')
                return True
    elif r.status_code == 403:
        print('Github请求过于频繁, 请稍后再试')
    print(f'入库失败: {app_id}')
    return False


def app(app_path):
    app_path = Path(app_path)
    if not app_path.is_dir():
        raise NotADirectoryError(app_path)
    steam_path = get_steam_path()
    app_id_list = list(filter(str.isdecimal, app_path.name.strip().split('-')))
    if not app_id_list:
        raise Exception('目录名称不是app_id')
    for file in app_path.iterdir():
        if file.is_file():
            if file.suffix == '.manifest':
                depot_cache_path = steam_path / 'depotcache'
                shutil.copy(file, depot_cache_path)
                print(f'导入清单成功: {file.name}')
            elif file.name == 'config.vdf':
                with file.open('r', encoding='utf-8') as f:
                    depots_config = vdf.loads(f.read())
                if depotkey_merge(steam_path / 'config' / 'config.vdf', depots_config):
                    print('合并config.vdf成功')
                if stool_add([(depot_id, '1',
                               depots_config['depots'][depot_id]['DecryptionKey']) for depot_id in
                              depots_config['depots']], app_id_list[0]):
                    print('导入steamtools成功')


parser = argparse.ArgumentParser()
parser.add_argument('-r', '--repo', default='isKoi/Manifest-AutoUpdate')
parser.add_argument('-a', '--app-id', nargs='+')
parser.add_argument('-p', '--app-path')
parser.add_argument('-g', '--greenluma', default=False, action='store_true')
parser.add_argument('-d', '--delete', default=False, action='store_true')
args = parser.parse_args()
repo = args.repo
if __name__ == '__main__':
    try:
        input('注意: 即将关闭steam, 输入回车确认')
        subprocess.run(['taskkill', '/f', '/im', 'steam.exe'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if args.app_path:
            app(args.app_path)
        else:
            app_id = args.app_id
            if not app_id:
                app_id = input('appid: ')
            for id in app_id:
                main(id)
            if args.greenluma and len(app_id) == 1:
                subprocess.run(f'start steam://install/{app_id}', shell=True)
            if not args.greenluma:
                subprocess.run('start steam://', shell=True)
    except KeyboardInterrupt:
        exit()
    except:
        traceback.print_exc()
    if not args.app_id and not args.app_path:
        os.system('pause')