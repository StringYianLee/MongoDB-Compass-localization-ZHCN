"""Generate Product.wxs for the CompassZhCn MSI (WiX v5)."""
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
DIST = ROOT / "dist"
EXE = ROOT / "dist_flet" / "CompassZhCnFlet.exe"

if not EXE.exists():
    raise SystemExit("请先构建 dist_flet/CompassZhCnFlet.exe")

UPGRADE_CODE = "5B0E7A41-9C2D-4F6B-8E13-7A4D2C9F6B58"
PRODUCT_CODE = "4F2E9B7C-8C13-4A6B-9E52-7D0B2A8F5C31"

files_root = [("CompassZhCn.exe", EXE), ("README.md", ROOT / "README.md")]
files_lang = [(p.name, p) for p in sorted((ROOT / "lang").iterdir()) if p.is_file()]
files_assets = [(p.name, p) for p in sorted((ROOT / "assets").iterdir()) if p.is_file()]
files_data = [(p.name, p) for p in sorted((ROOT / "data").iterdir()) if p.is_file()]
files_docs = [(p.name, p) for p in sorted((ROOT / "docs").iterdir()) if p.is_file()]


def comp_id(rel: str) -> str:
    return "cmp_" + uuid.uuid5(uuid.NAMESPACE_URL, "compasszhcn/" + rel).hex[:16]


def comp_guid(rel: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "compasszhcn/component/" + rel)).upper()


def file_id(rel: str) -> str:
    return "fil_" + uuid.uuid5(uuid.NAMESPACE_URL, "compasszhcn/file/" + rel).hex[:16]


def file_elems(items, subdir: str, prefix: str, install_names=None):
    out = []
    install_names = install_names or {}
    for i, (name, src) in enumerate(items):
        rel = f"{prefix}/{name}" if prefix else name
        attrs = f'Id="{file_id(rel)}" Source="{src}"'
        if rel in install_names:
            attrs += f' Name="{install_names[rel]}"'
        if i == 0:
            attrs += ' KeyPath="yes"'
        out.append(f"        <File {attrs} />")
    return "\n".join(out)


root_comp = f"""      <Component Id="{comp_id('root')}" Directory="INSTALLFOLDER" Guid="{comp_guid('root')}">
{file_elems(files_root, 'INSTALLFOLDER', '', {'CompassZhCn.exe': 'CompassZhCn.exe'})}
        <RemoveFolder Id="RemoveInstallFolder" On="uninstall" />
      </Component>"""

lang_comp = f"""      <Component Id="{comp_id('lang')}" Directory="LangFolder" Guid="{comp_guid('lang')}">
{file_elems(files_lang, 'LangFolder', 'lang')}
      </Component>"""

assets_comp = f"""      <Component Id="{comp_id('assets')}" Directory="AssetsFolder" Guid="{comp_guid('assets')}">
{file_elems(files_assets, 'AssetsFolder', 'assets')}
      </Component>"""

data_comp = f"""      <Component Id="{comp_id('data')}" Directory="DataFolder" Guid="{comp_guid('data')}">
{file_elems(files_data, 'DataFolder', 'data')}
      </Component>"""

docs_comp = f"""      <Component Id="{comp_id('docs')}" Directory="DocsFolder" Guid="{comp_guid('docs')}">
{file_elems(files_docs, 'DocsFolder', 'docs')}
      </Component>"""

wxs = f"""<?xml version="1.0" encoding="utf-8"?>
<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs"
     xmlns:ui="http://wixtoolset.org/schemas/v4/wxs/ui">
  <Package Name="MongoDB Compass 汉化工具"
           Manufacturer="CompassZhCn"
           Version="2.0.0"
           Language="2052"
           Codepage="936"
           UpgradeCode="{UPGRADE_CODE}"
           ProductCode="{PRODUCT_CODE}"
           Scope="perUser"
           Compressed="yes"
           InstallerVersion="500">

    <Property Id="ALLUSERS" Value="2" />
    <Property Id="MSIINSTALLPERUSER" Value="1" />

    <CustomAction Id="SetArpInstallLocation" Property="ARPINSTALLLOCATION" Value="[INSTALLFOLDER]" Execute="immediate" />
    <InstallExecuteSequence>
      <Custom Action="SetArpInstallLocation" After="CostFinalize" Condition="NOT Installed" />
    </InstallExecuteSequence>

    <MajorUpgrade DowngradeErrorMessage="已安装更新版本的 Compass 汉化工具，请先在“应用和功能”中卸载。" />
    <MediaTemplate EmbedCab="yes" />

    <Icon Id="AppIcon" SourceFile="..\\assets\\compass.ico" />
    <Property Id="ARPPRODUCTICON" Value="AppIcon" />
    <Property Id="WIXUI_INSTALLDIR" Value="INSTALLFOLDER" />
    <Property Id="WIXUI_EXITDIALOGOPTIONALTEXT" Value="安装完成。可从开始菜单或桌面快捷方式启动。" />
    <WixVariable Id="WixUILicenseRtf" Value="License.rtf" />
    <ui:WixUI Id="WixUI_InstallDir" />

    <Feature Id="MainFeature" Title="Compass 汉化工具" Level="1">
      <ComponentGroupRef Id="AppComponents" />
      <ComponentGroupRef Id="ShortcutComponents" />
    </Feature>
  </Package>

  <Fragment>
    <StandardDirectory Id="LocalAppDataFolder">
      <Directory Id="ProgramsFolder" Name="Programs">
        <Directory Id="INSTALLFOLDER" Name="Compass汉化工具">
          <Directory Id="LangFolder" Name="lang" />
          <Directory Id="AssetsFolder" Name="assets" />
          <Directory Id="DataFolder" Name="data" />
          <Directory Id="DocsFolder" Name="docs" />
        </Directory>
      </Directory>
    </StandardDirectory>
  </Fragment>

  <Fragment>
    <ComponentGroup Id="AppComponents">
{root_comp}
{lang_comp}
{assets_comp}
{data_comp}
{docs_comp}
    </ComponentGroup>
  </Fragment>

  <Fragment>
    <ComponentGroup Id="ShortcutComponents">
      <Component Id="cmp_startmenu" Directory="ProgramMenuFolder" Guid="{comp_guid('startmenu')}">
        <Shortcut Id="StartMenuShortcut"
                  Name="MongoDB Compass 汉化工具"
                  Description="汉化 MongoDB Compass，并支持一键还原"
                  Target="[INSTALLFOLDER]CompassZhCn.exe"
                  WorkingDirectory="INSTALLFOLDER"
                  Icon="AppIcon" />
        <RemoveFolder Id="RemoveStartMenuFolder" On="uninstall" />
        <RegistryValue Root="HKCU" Key="Software\\CompassZhCn" Name="StartMenu" Type="integer" Value="1" KeyPath="yes" />
      </Component>
      <Component Id="cmp_desktop" Directory="DesktopFolder" Guid="{comp_guid('desktop')}">
        <Shortcut Id="DesktopShortcut"
                  Name="MongoDB Compass 汉化工具"
                  Description="汉化 MongoDB Compass，并支持一键还原"
                  Target="[INSTALLFOLDER]CompassZhCn.exe"
                  WorkingDirectory="INSTALLFOLDER"
                  Icon="AppIcon" />
        <RegistryValue Root="HKCU" Key="Software\\CompassZhCn" Name="Desktop" Type="integer" Value="1" KeyPath="yes" />
      </Component>
    </ComponentGroup>
  </Fragment>
</Wix>
"""
(BASE / "Product.wxs").write_text(wxs, encoding="utf-8")
print("Product.wxs written:", len(wxs), "bytes")
print("files:", len(files_root), len(files_lang), len(files_assets), len(files_data), len(files_docs))
