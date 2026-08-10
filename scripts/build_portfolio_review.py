#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成独立持仓复盘报告 portfolio-review-YYYYMMDD.html
参考样式：星辰决策仪表盘 portfolio-review 页面
"""
import portfolio_report_core


def build():
    return portfolio_report_core.build_full_page()


if __name__ == "__main__":
    build()
