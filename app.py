import streamlit as st
import pdfplumber
import re
import urllib.parse
import googlemaps
import pytesseract
from PIL import Image
import io
import base64
import uuid
import requests
from bs4 import BeautifulSoup

# --- 頁面配置 ---
st.set_page_config(page_title="昭佑的房仲文案戰鬥面板", layout="wide", initial_sidebar_state="expanded")

# --- 核心數據抓取邏輯 ---
def parse_real_estate_text(full_text):
    data = {}
    
    # 金額處理 (包含 591 常見的 "1,200 萬" 格式)
    clean_text_for_price = full_text.replace(",", "")
    all_prices = re.findall(r"(\d{3,5})[\s\n售價]*萬", clean_text_for_price)
    data['price'] = str(max([int(p) for p in all_prices])) if all_prices else ""
    
    addr_match = re.search(r"(?:物件)?(?:地址|位置|座落|門牌)[:：\s]*(.*?)(?=[\n\(（]|電話|$)", full_text)
    address = addr_match.group(1).strip() if addr_match else ""
    if not address:
        tw_match = re.search(r"([A-Z\u4e00-\u9fa5]{2,3}[縣市][A-Z\u4e00-\u9fa5]{2,3}[鄉鎮市區].+?[路街段].+?號)", full_text)
        address = tw_match.group(1) if tw_match else ""
        
    if "號" in address:
        clean_address = address.split("號")[0] + "號"
    else:
        clean_address = re.sub(r"(\d+[Ff樓]|之\d+|-\d+).*$", "", address)
    data['address'] = address
    data['nav_address'] = clean_address.strip()
    
    def find_val(keyword, text):
        match = re.search(rf"{keyword}[:：\s]*([\d\.]+)坪", text)
        return match.group(1) if match else ""
        
    data['main'] = find_val("(?:主建物|室內)", full_text)
    data['sub'] = find_val("附屬建物", full_text)
    data['public'] = find_val("(?:公\s*設|共有部分)", full_text) 
    data['parking'] = find_val("車\s*位", full_text)
    
    # 總坪數 (包含 591 的 "權狀坪數")
    total_match = re.search(r"(?:總坪數|權狀坪數)[:：\s]*([\d\.]+)坪", full_text)
    data['total'] = total_match.group(1) if total_match else find_val("總坪數", full_text)
    
    ratio_match = re.search(r"公設比[:：\s]*([\d\.]+)%", full_text)
    data['ratio'] = ratio_match.group(1) if ratio_match else ""
    
    floor_match = re.search(r"總樓層[:：\s]*(\d+)層.*出售樓層[:：\s]*(\d+)層", full_text, re.S)
    if not floor_match:
        # 抓取 591 常見格式 "樓層 2F/15F"
        floor_match = re.search(r"樓層[:：\s]*(\d+)[Ff樓]\s*/\s*(\d+)[Ff樓]", full_text)
        data['floor'] = f"{floor_match.group(1)}/{floor_match.group(2)} 樓" if floor_match else ""
    else:
        data['floor'] = f"{floor_match.group(2)}/{floor_match.group(1)} 樓"

    age_match = re.search(r"(?:屋齡|建築完成日)[:：\s]*([0-9\./年]+)", full_text)
    data['age'] = age_match.group(1).strip() if age_match else ""
    
    fee_match = re.search(r"管理費[:：\s]*([0-9,]+)", full_text)
    data['fee'] = fee_match.group(1).strip() if fee_match else ""
    
    ori_match = re.search(r"(?:座向|面向|朝向)[:：\s]*([座朝東西南北]+)", full_text)
    data['orientation'] = ori_match.group(1).strip() if ori_match else ""

    return data

@st.cache_data
def process_uploaded_file(file_bytes, file_name):
    full_text = ""
    file_type = file_name.split('.')[-1].lower()
    if file_type == 'pdf':
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text: full_text += text + "\n"
    elif file_type in ['jpg', 'jpeg', 'png']:
        image = Image.open(io.BytesIO(file_bytes))
        full_text = pytesseract.image_to_string(image, lang='chi_tra') 
    return parse_real_estate_text(full_text), full_text

# ✨ 新增：網址爬蟲處理功能 (加入快取)
@st.cache_data
def process_url(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 移除干擾的程式碼標籤
        for script in soup(["script", "style"]):
            script.extract()
            
        # 提取網頁所有文字
        raw_text = soup.get_text(separator='\n', strip=True)
        return parse_real_estate_text(raw_text), raw_text
    except Exception as e:
        return None, str(e)

@st.cache_data
def generate_preview_html(file_bytes, file_name):
    file_type = file_name.split('.')[-1].lower()
    image = None
    if file_type in ['jpg', 'jpeg', 'png']:
        image = Image.open(io.BytesIO(file_bytes))
    elif file_type == 'pdf':
        try:
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                image = pdf.pages[0].to_image(resolution=150).original
        except Exception:
            return "📄 PDF 已上傳 (右側數據分析正常運作中)"
            
    if image:
        if image.mode != 'RGB': image = image.convert('RGB')
        buffered = io.BytesIO()
        image.save(buffered, format="JPEG")
        img_b64 = base64.b64encode(buffered.getvalue()).decode()
        uid = str(uuid.uuid4())[:8]
        
        html_code = f"""<div id="container-{uid}" style="overflow: hidden; cursor: zoom-in; border-radius: 8px; border: 1px solid #ddd; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
            <img id="img-{uid}" src="data:image/jpeg;base64,{img_b64}" style="width: 100%; transition: transform 0.1s ease;">
        </div>
        <script>
            (function() {{
                const container = document.getElementById('container-{uid}');
                const img = document.getElementById('img-{uid}');
                container.addEventListener('mousemove', function(e) {{
                    const rect = container.getBoundingClientRect();
                    const x = ((e.clientX - rect.left) / rect.width) * 100;
                    const y = ((e.clientY - rect.top) / rect.height) * 100;
                    img.style.transformOrigin = x + '% ' + y + '%';
                    img.style.transform = 'scale(2.5)'; 
                }});
                container.addEventListener('mouseleave', function() {{
                    img.style.transform = 'scale(1)';
                    img.style.transformOrigin = 'center center';
                }});
            }})();
        </script>
        <p style="color: gray; font-size: 14px; margin-top: 8px;">🔍 提示：將滑鼠移至上方圖片，即可像放大鏡般檢視字體與細節！</p>
        """
        return html_code
    return ""

KEYWORD_OPTIMIZER = {
    "全聯": "全聯福利中心", "家樂福": "家樂福", "國民小學": "國小", "國民中學": "國中",
    "高中": "高中", "大學": "大學", "便利商店": "便利商店", "交流道": "交流道",
    "幼稚園": "幼兒園", "托嬰中心": "托嬰中心", "親子館": "親子館", "公園": "公園", "捷運站": "捷運站"
}

# --- UI 介面 ---
st.sidebar.title("⚙️ 系統設定與輸入")
api_key = st.sidebar.text_input("🔑 Google Maps API Key", type="password")

st.sidebar.markdown("---")
# ✨ 新增網址輸入框
target_url = st.sidebar.text_input("🔗 貼上房屋網址 (如 591 連結自動抓取)")
st.sidebar.markdown("<div style='text-align: center; color: gray;'>或</div>", unsafe_allow_html=True)
uploaded_file = st.sidebar.file_uploader("📂 上傳物件資料表", type=['pdf', 'jpg', 'jpeg', 'png'])

col_left, col_right = st.columns([3, 7])
auto_data = {}
extracted_raw_text = ""

with col_left:
    st.header("👁️ 原始資料預覽")
    
    # 判斷是使用網址還是上傳檔案
    if target_url:
        with st.spinner("🌐 正在潛入網頁抓取資料中..."):
            auto_data, extracted_raw_text = process_url(target_url)
            if auto_data is not None:
                st.success("✅ 網址解析完成！已盡量從網頁中萃取數據。")
                st.info("💡 提示：網頁抓取不會產生圖片預覽，請直接核對右側面板數據。")
                st.markdown(f"👉 [點擊此處開啟原網頁]({target_url})")
            else:
                st.error(f"❌ 網址解析失敗，可能是網站阻擋爬蟲。錯誤訊息：{extracted_raw_text}")
                
    elif uploaded_file:
        file_bytes = uploaded_file.getvalue()
        preview_content = generate_preview_html(file_bytes, uploaded_file.name)
        
        if "<div" in preview_content:
            st.markdown(preview_content, unsafe_allow_html=True)
        else:
            st.warning(preview_content)
            
        auto_data, extracted_raw_text = process_uploaded_file(file_bytes, uploaded_file.name)
    else:
        st.info("請於左側輸入網址，或上傳檔案。")

with col_right:
    st.title("🏠 房仲文案戰鬥面板")
    st.header("1. 確認房屋詳細資訊")
    r_col1, r_col2, r_col3 = st.columns(3)
    
    with r_col1:
        address = st.text_input("📍 物件地址", value=auto_data.get('address', ''))
        nav_base = st.text_input("📍 導航起點", value=auto_data.get('nav_address', ''))
        price = st.text_input("💰 開價 (萬)", value=auto_data.get('price', ''))
        property_type = st.selectbox("🏢 建物型態", ["電梯大樓", "華廈", "公寓", "透天厝", "店面", "廠房", "土地"])
        age = st.text_input("📅 屋齡/完成日", value=auto_data.get('age', ''), placeholder="例如：5年 或 108/05/20")
        
    with r_col2:
        total_area = st.text_input("📐 總坪數", value=auto_data.get('total', ''))
        main_area = st.text_input("🏠 主建物", value=auto_data.get('main', ''))
        sub_area = st.text_input("🧺 附屬建物", value=auto_data.get('sub', ''))
        public_area = st.text_input("🏢 公設", value=auto_data.get('public', ''))
        public_ratio = st.text_input("📊 公設比 (%)", value=auto_data.get('ratio', ''))
        
    with r_col3:
        floor_info = st.text_input("🏙️ 樓層", value=auto_data.get('floor', ''))
        orientation = st.text_input("🧭 面向", value=auto_data.get('orientation', ''), placeholder="例如：座南朝北")
        parking_type = st.selectbox("🅿️ 車位類型", ["無", "坡道平面", "坡道機械", "升降平面", "升降機械", "一樓車庫", "庭院車位"])
        parking_area = st.text_input("🚗 車位坪數", value=auto_data.get('parking', ''))
        management_fee = st.text_input("💵 管理費", value=auto_data.get('fee', ''), placeholder="例如：2500元/月")

    st.write("---")
    st.header("2. 🗺️ 周邊機能精準搜尋")
    standard_amenities = {
        "🛒 採買": ["全聯", "家樂福", "便利商店", "傳統市場"],
        "🚆 交通": ["捷運站", "交流道", "公車站"],
        "🌳 休閒": ["公園", "運動中心", "親子館"],
        "🏫 教育": ["國民小學", "國民中學", "高中", "大學"],
        "👶 育兒": ["幼稚園", "托嬰中心"]
    }
    c_a, c_b, c_c, c_d, c_e = st.columns(5)
    with c_a: sel_shopping = st.multiselect("🛒 採買", standard_amenities["🛒 採買"])
    with c_b: sel_traffic = st.multiselect("🚆 交通", standard_amenities["🚆 交通"])
    with c_c: sel_park = st.multiselect("🌳 休閒", standard_amenities["🌳 休閒"])
    with c_d: sel_school = st.multiselect("🏫 教育", standard_amenities["🏫 教育"])
    with c_e: sel_baby = st.multiselect("👶 育兒", standard_amenities["👶 育兒"])
    selected_list = sel_shopping + sel_traffic + sel_park + school + sel_baby

    auto_fetched_data = {}
    if api_key and selected_list and nav_base:
        if st.button("⚡ 啟動衛星雷達掃描", type="primary"):
            gmaps = googlemaps.Client(key=api_key)
            geocode_result = gmaps.geocode(nav_base, language='zh-TW')
            if geocode_result:
                loc = geocode_result[0]['geometry']['location']
                for item in selected_list:
                    search_keyword = KEYWORD_OPTIMIZER.get(item, item)
                    places_result = gmaps.places_nearby(location=(loc['lat'], loc['lng']), keyword=search_keyword, rank_by="distance", language='zh-TW')
                    valid_places = [p for p in places_result.get('results', []) if "補習班" not in p.get('name', '') and "安親班" not in p.get('name', '')]
                    if valid_places:
                        best_place = valid_places[0]
                        matrix = gmaps.distance_matrix(origins=(loc['lat'], loc['lng']), destinations=(best_place['geometry']['location']['lat'], best_place['geometry']['location']['lng']), mode="walking", language='zh-TW')
                        if matrix['rows'][0]['elements'][0]['status'] == 'OK':
                            dist_t = matrix['rows'][0]['elements'][0]['distance']['text']
                            auto_fetched_data[item] = {"name": best_place['name'], "dist_val": re.sub(r'[^\d\.]', '', dist_t), "dist_unit": "公里" if "km" in dist_t.lower() else "公尺", "time": re.sub(r'[^\d]', '', matrix['rows'][0]['elements'][0]['duration']['text']), "lat": best_place['geometry']['location']['lat'], "lng": best_place['geometry']['location']['lng']}

    amenity_details = {}
    if selected_list:
        st.write("### ⏱️ 周邊機能細節設定")
        for item in selected_list:
            col_n, col_m, col_d, col_u, col_t = st.columns([2, 1, 1, 1, 1])
            fetched = auto_fetched_data.get(item, {})
            with col_n:
                r_name = st.text_input(f"設施 ({item})", value=fetched.get("name", item), key=f"n_{item}")
                if nav_base:
                    dest = f"{fetched['lat']},{fetched['lng']}" if "lat" in fetched else urllib.parse.quote(f"{nav_base} {KEYWORD_OPTIMIZER.get(item, item)}")
                    st.markdown(f'<a href="https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(nav_base)}&destination={dest}&travelmode=walking" target="_blank" style="color:#1E90FF; font-size:12px;">📍導航確認</a>', unsafe_allow_html=True)
            with col_m: method = st.selectbox("方式", ["步行", "開車", "騎車"], key=f"m_{item}")
            with col_d: dist_v = st.text_input("距離", value=fetched.get("dist_val", ""), key=f"d_{item}")
            with col_u: dist_u = st.selectbox("單位", ["公尺", "公里"], index=0 if fetched.get("dist_unit") == "公尺" else 1, key=f"u_{item}")
            with col_t: time_v = st.text_input("分鐘", value=fetched.get("time", "5"), key=f"t_{item}")
            amenity_details[item] = f"{method}約 {dist_v} {dist_u} {time_v} 分鐘可達 {r_name}"

    st.write("---")
    st.header("3. ✨ 房屋優勢與風格")
    adv_col1, adv_col2 = st.columns(2)
    with adv_col1:
        advs = [st.text_input(f"🌟 優勢 {i+1}") for i in range(3)]
    with adv_col2:
        advs += [st.text_input(f"🌟 優勢 {i+4}") for i in range(2)]
    
    ad_style = st.selectbox("🎭 文案風格", ["溫馨家庭風", "霸氣尊榮風", "投資精算風", "誠懇務實風", "✏️ 自訂"])
    c_intro = st.text_area("✍️ 自訂開場") if "自訂" in ad_style else ""

    st.write("---")
    st.header("4. 👤 聯絡資訊")
    con1, con2 = st.columns(2)
    with con1:
        u_name, u_phone, u_line = st.text_input("👤 姓名", "劉昭佑"), st.text_input("📞 電話", "0938-888-906"), st.text_input("📲 Line", "https://line.me/ti/p/cUeRQgiigK")
    with con2:
        u_store, u_license = st.text_input("🏪 店名", "捷運樂善直營店"), st.text_input("🪪 字號")

    if st.button("✨ 一鍵生成廣告", type="primary"):
        styles = {"溫馨家庭風": ("【這不是賣房子，是為您尋找更好的生活】", "現場的溫度才是房子的靈魂。"), "霸氣尊榮風": ("【頂級視野，專屬品味】", "尊榮感親臨現場方能領略。"), "投資精算風": ("【精準眼光，資產翻倍】", "數字會說話，搶佔增值先機。"), "誠懇務實風": ("【實實在在的好房子】", "陪您挑選最適合的家。")}
        intro, outro = (c_intro, "") if "自訂" in ad_style else styles.get(ad_style)
        
        adv_txt = "--- ✨ 本案優勢 ---\n" + "\n".join([f"🔥 {a}" for a in advs if a]) + "\n\n" if any(advs) else ""
        ame_txt = "--- 📍 周邊機能 ---\n" + "\n".join([f"✅ {v}" for v in amenity_details.values()]) + "\n\n" if amenity_details else ""
        
        parking_text = f"{parking_type} ({parking_area} 坪)" if parking_area else parking_type
        
        final_text = f"""
{intro}

{adv_txt}{ame_txt}--- 🏠 房屋資訊 ---
📍 型態：{property_type}
📍 總坪數：{total_area} 坪
📍 主建物：{main_area} 坪
📍 附屬建物：{sub_area} 坪
📍 公設：{public_area} 坪 (公設比約 {public_ratio}%)
📍 車位：{parking_text}
📍 樓層：{floor_info}
📍 屋齡：{age}
📍 面向：{orientation}
📍 管理費：{management_fee}
💰 開價：{price} 萬

{outro}

--- 🙋‍♂️ 聯絡資訊 ---
📞 {u_phone} ({u_name})
📲 {u_line}

台灣房屋 {u_store}
專屬顧問：{u_name} {u_license}

🅣 經紀業：台灣房屋仲介股份有限公司
🅣 經紀人：康博超 桃市經字第001240號
"""
        st.text_area("結果", value=final_text.strip(), height=600)
