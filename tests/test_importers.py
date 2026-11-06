import pytest
from openpyxl import Workbook
from justvedio.importers import load_identities
from justvedio.models import SiteConfig, VideoOptions, DEFAULT_VIDEO_URL

def test_original_excel_format_precision_and_duplicates(tmp_path):
    wb = Workbook()
    ws = wb.create_sheet('身份')
    ws.append(['所在的区县','姓名','身份证号'])
    ws.append(['黔江区','演示甲','11010119900101001x'])
    ws.append(['黔江区','演示乙',110101199001010010])
    ws.append(['黔江区','演示丙','bad-id'])
    ws.append(['黔江区','重复甲','11010119900101001X'])
    path = tmp_path/'people.xlsx'
    wb.save(path)
    result = load_identities(str(path))
    assert len(result.candidates) == 1 and len(result.rejected) == 3
    assert result.sheet == '身份' and result.candidates[0].id_number.endswith('X')
    assert '19900101' not in result.candidates[0].masked_id
    assert any('重复' in issue for issue in result.issues)
    assert any('精度' in issue for issue in result.issues)

@pytest.mark.parametrize('url',['http://ks.cqsdx.cn/exam/','https://evil.example/exam/','https://ks.cqsdx.cn.evil.example/exam/'])
def test_login_destination_unchanged(url):
    with pytest.raises(ValueError):
        SiteConfig(url).validate()

def test_bilibili_default_and_future_site_mode():
    options = VideoOptions()
    options.validate(SiteConfig())
    assert options.concurrency == 10 and 'BV14zJY6WExr' in DEFAULT_VIDEO_URL
    VideoOptions(video_url='',entry_selector='text=观看视频').validate(SiteConfig())

@pytest.mark.parametrize('url',['file:///secret.mp4','javascript:alert(1)','https://user:pass@example.com/video'])
def test_bad_video_urls_rejected(url):
    with pytest.raises(ValueError):
        VideoOptions(video_url=url).validate(SiteConfig())


def test_folder_merges_identity_files_and_rejects_duplicates(tmp_path):
    from justvedio.importers import load_identity_folder
    folder = tmp_path/'人员信息'
    folder.mkdir()
    first = Workbook()
    sheet = first.active
    sheet.append(['所在的区县','姓名','身份证号'])
    sheet.append(['黔江区','甲','110101199001010011'])
    sheet.append(['黔江区','乙','110101199001010022'])
    first.save(folder/'a.xlsx')
    first.close()
    second = Workbook()
    sheet = second.active
    sheet.append(['所在的区县','姓名','身份证号'])
    sheet.append(['黔江区','丙','110101199001010022'])
    sheet.append(['黔江区','丁','110101199001010033'])
    second.save(folder/'b.xlsx')
    second.close()
    result = load_identity_folder(str(folder))
    assert [c.name for c in result.candidates] == ['甲', '乙', '丁']
    assert result.sheet == '2 个文件'
    assert any('重复' in issue for issue in result.issues)
    assert len(result.rejected) == 1


def test_empty_folder_is_rejected(tmp_path):
    from justvedio.importers import load_identity_folder
    folder = tmp_path/'人员信息'
    folder.mkdir()
    with pytest.raises(ValueError, match='没有'):
        load_identity_folder(str(folder))
