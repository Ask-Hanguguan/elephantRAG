"""
全局自定义样式
================================================
统一 CSS 注入，避免各页面内嵌冗长样式。
"""
import streamlit as st

# ============================================================
# 全局主题 CSS
# ============================================================
GLOBAL_CSS = """
<style>
/* ---- 基础变量 ---- */
:root {
    --primary: #4F6EF7;
    --primary-light: #6B85F9;
    --primary-dark: #3A54D4;
    --bg-main: #F5F7FB;
    --bg-card: #FFFFFF;
    --bg-sidebar: #FAFBFF;
    --text-primary: #1A202C;
    --text-secondary: #64748B;
    --text-muted: #94A3B8;
    --border-color: #E2E8F0;
    --success: #10B981;
    --warning: #F59E0B;
    --danger: #EF4444;
    --shadow-sm: 0 1px 3px rgba(0,0,0,0.06);
    --shadow-md: 0 4px 12px rgba(0,0,0,0.08);
    --shadow-lg: 0 8px 24px rgba(0,0,0,0.12);
    --radius: 12px;
    --radius-sm: 8px;
}

/* ---- 全局背景 ---- */
.stApp {
    background-color: var(--bg-main) !important;
}

/* ---- 隐藏默认元素 ---- */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header[data-testid="stHeader"] {visibility: hidden;}

/* ---- 主内容区 ---- */
.main .block-container {
    padding-top: 2rem;
    max-width: 960px;
}

/* ---- 标签页 ---- */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    background: var(--bg-card);
    padding: 4px;
    border-radius: var(--radius);
    box-shadow: var(--shadow-sm);
}

.stTabs [data-baseweb="tab"] {
    border-radius: var(--radius-sm);
    padding: 8px 20px;
    font-weight: 500;
    color: var(--text-secondary);
    transition: all 0.2s ease;
}

.stTabs [aria-selected="true"] [data-baseweb="tab"] {
    background: var(--primary);
    color: white;
    border-radius: var(--radius-sm);
    box-shadow: 0 2px 6px rgba(79,110,247,0.3);
}

/* ---- 聊天气泡 ---- */
.stChatMessage {
    background: var(--bg-card);
    border-radius: var(--radius);
    box-shadow: var(--shadow-sm);
    padding: 1rem 1.25rem;
    border: 1px solid var(--border-color);
}

/* ---- 侧边栏按钮单行截断 ---- */
[data-testid="stSidebar"] .stButton button {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    padding: 0.3rem 0.6rem;
    font-size: 0.85rem;
    border-radius: 6px;
}

/* 侧边栏分行容器紧凑 */
[data-testid="stSidebar"] .stHorizontalBlock {
    gap: 0.3rem !important;
    margin-bottom: 0.2rem;
}
</style>
"""

# ============================================================
# 聊天页欢迎屏
# ============================================================
WELCOME_CSS = """
<style>
.welcome-center {
    text-align: center;
    margin-top: 15vh;
    margin-bottom: 5vh;
}

.welcome-center .welcome-icon {
    font-size: 4rem;
    margin-bottom: 0;
}

.welcome-center h2 {
    font-size: 1.6rem;
    font-weight: 700;
    color: #1A202C;
    margin-bottom: 0.3rem;
}

.welcome-center p {
    color: #888;
    font-size: 1rem;
}
</style>
"""


def inject_global_css():
    """注入全局基础样式（所有页面共享）"""
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def inject_welcome_css():
    """注入聊天页欢迎屏样式"""
    st.markdown(WELCOME_CSS, unsafe_allow_html=True)
