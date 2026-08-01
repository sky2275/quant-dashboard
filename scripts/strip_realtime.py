"""从已注入 v1 实时逻辑的 index.html 中剔除 v1 注入，恢复为干净的数据基线。
用于在同一份数据文件上重新注入升级版（v2）实时逻辑，避免重复注入。
"""
P = "index.html"
html = open(P, encoding="utf-8").read()

# 1) 删除 v1 RT_JS 块（从 style IIFE 起始到最后一个 </script> 之前）
marker = "(function(){\n  var s=document.createElement('style');"
if marker in html:
    start = html.index(marker)
    end = html.rfind("</script>")
    html = html[:start] + html[end:]
    print("STRIP_RT_JS ok")
else:
    print("RT_JS marker NOT found, skip")

# 2) 删除 v1 rtStatus 徽章
import re
html = re.sub(r'<span class="live-badge off" id="rtStatus">.*?</span>\n?', '', html)

# 3) 还原 loadIndexSpark(); 调用（去掉 startRealtime 插入）
html = html.replace('loadIndexSpark();\n    startRealtime();', 'loadIndexSpark();')

open(P, "w", encoding="utf-8").write(html)
print("STRIP_DONE push2=", html.count("push2.eastmoney"),
      "rtStatus=", html.count('id="rtStatus"'),
      "startRealtime=", html.count("startRealtime"),
      "picks=", html.count('data-code="[0-9]'.replace('[0-9]', '[0-9]')))
