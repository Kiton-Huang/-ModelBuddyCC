"""
ModelBuddyCC — Claude Code 模型配置管理器
一键切换 .claude.json 中的 env 配置（API地址、密钥、模型名）
支持多配置记忆与快速切换
"""
from app.main_window import ModelSwitcherApp

if __name__ == "__main__":
    app = ModelSwitcherApp()
    app.mainloop()
