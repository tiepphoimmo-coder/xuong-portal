#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI tao thanh vien portal. In token tho DUY NHAT 1 lan.

Vi du:
  python create_user.py an --role admin
  python create_user.py binh          (mac dinh member)
Dat DATA_HOME de ghi vao data cua portal:
  DATA_HOME=/opt/xuong-portal/data python create_user.py an --role admin
"""
import sys, argparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import auth


def main():
    p = argparse.ArgumentParser(description="Tao user portal (in token 1 lan).")
    p.add_argument("user", help="ten dang nhap")
    p.add_argument("--role", default="member", choices=["admin", "member"])
    p.add_argument("--token", default=None, help="dat token co san (mac dinh sinh ngau nhien)")
    a = p.parse_args()
    rec, tok = auth.create_user(a.user, a.role, a.token)
    print("=" * 48)
    print(f"  User : {rec['user']}")
    print(f"  Role : {rec['role']}")
    print(f"  Data : {auth.store.DATA}")
    print(f"  TOKEN: {tok}")
    print("  (Luu token lai — chi hien 1 lan. Dang nhap = user + token.)")
    print("=" * 48)


if __name__ == "__main__":
    main()
