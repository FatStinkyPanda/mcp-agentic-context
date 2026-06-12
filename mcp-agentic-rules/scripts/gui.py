"""
MCP Agentic Context Local Web GUI Dashboard (Zero-Dependency)
===================================================
Launches a gorgeous local web server and single page application for
managing, indexing, diagnosing, and repairing mcp-agentic-context.

Usage:
    python mcp.py gui
    python mcp.py gui --port 8550
"""

from datetime import datetime
import http.server
from typing import Dict, List, Optional
import json
import os
from pathlib import Path
import socket
import socketserver
import sys
import threading
import time
import urllib.parse
import webbrowser
import subprocess
import uuid
import hashlib

from .utils import Console, find_project_root
from .doctor import Doctor
from .memory import MemoryStore, Memory

# HTML Dashboard Content
HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MCP Agentic Context Dashboard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;500;600;700;800&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-base: #0a0c10;
            --bg-surface: #121620;
            --bg-card: rgba(23, 29, 43, 0.7);
            --bg-card-hover: rgba(30, 38, 56, 0.9);
            --border-card: rgba(255, 255, 255, 0.06);
            --border-card-hover: rgba(0, 229, 255, 0.3);
            
            --color-primary: #00e5ff;
            --color-primary-glow: rgba(0, 229, 255, 0.15);
            --color-success: #00e676;
            --color-success-glow: rgba(0, 230, 118, 0.15);
            --color-warning: #ffd700;
            --color-warning-glow: rgba(255, 215, 0, 0.15);
            --color-error: #ff5252;
            --color-error-glow: rgba(255, 82, 82, 0.15);
            
            --text-main: #e2e8f0;
            --text-muted: #8a99ad;
            --text-bright: #ffffff;
            
            --font-display: 'Outfit', sans-serif;
            --font-sans: 'Inter', sans-serif;
            --font-mono: 'Fira Code', monospace;
            
            --transition-smooth: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg-base);
            background-image: 
                radial-gradient(at 0% 0%, rgba(0, 229, 255, 0.05) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(0, 230, 118, 0.03) 0px, transparent 50%);
            background-attachment: fixed;
            color: var(--text-main);
            font-family: var(--font-sans);
            line-height: 1.5;
            min-height: 100vh;
            overflow-x: hidden;
            padding-bottom: 40px;
        }

        h1, h2, h3, h4 {
            font-family: var(--font-display);
            font-weight: 600;
            color: var(--text-bright);
        }

        /* Layout */
        .container {
            max-width: 1300px;
            margin: 0 auto;
            padding: 24px;
        }

        /* Header styling */
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 24px;
            border-bottom: 1px solid var(--border-card);
            margin-bottom: 30px;
            gap: 20px;
        }

        .header-title-section {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .header-logo {
            width: 44px;
            height: 44px;
            background: linear-gradient(135deg, var(--color-primary), #00b0ff);
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-family: var(--font-display);
            font-weight: 800;
            font-size: 24px;
            color: var(--bg-base);
            box-shadow: 0 0 20px rgba(0, 229, 255, 0.3);
            user-select: none;
        }

        .header-text h1 {
            font-size: 26px;
            letter-spacing: -0.5px;
            margin-bottom: 4px;
        }

        .header-text p {
            font-size: 13px;
            color: var(--text-muted);
            font-family: var(--font-mono);
        }

        /* Dashboard Grid Layout */
        .grid-dashboard {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
            margin-bottom: 24px;
        }

        @media (max-width: 968px) {
            .grid-dashboard {
                grid-template-columns: 1fr;
            }
        }

        /* Custom Cards */
        .card {
            background-color: var(--bg-card);
            border: 1px solid var(--border-card);
            border-radius: 16px;
            padding: 24px;
            backdrop-filter: blur(12px);
            transition: var(--transition-smooth);
            display: flex;
            flex-direction: column;
            position: relative;
            overflow: hidden;
        }

        .card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 4px;
            background: transparent;
            transition: var(--transition-smooth);
        }

        .card:hover {
            border-color: var(--border-card-hover);
            transform: translateY(-2px);
            box-shadow: 0 12px 30px rgba(0, 229, 255, 0.04);
        }

        .card-title-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }

        .card-title-bar h2 {
            font-size: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        /* Health circular progress score */
        .health-circle-container {
            display: flex;
            align-items: center;
            gap: 20px;
            background: rgba(255, 255, 255, 0.02);
            padding: 16px 20px;
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.03);
            margin-bottom: 16px;
        }

        .health-circle {
            position: relative;
            width: 70px;
            height: 70px;
            border-radius: 50%;
            background: conic-gradient(var(--color-primary) var(--health-deg, 0deg), rgba(255, 255, 255, 0.06) 0deg);
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 0 15px var(--color-primary-glow);
        }

        .health-circle::after {
            content: '';
            position: absolute;
            width: 58px;
            height: 58px;
            background-color: var(--bg-surface);
            border-radius: 50%;
        }

        .health-score-val {
            position: relative;
            z-index: 2;
            font-family: var(--font-display);
            font-size: 20px;
            font-weight: 700;
            color: var(--text-bright);
        }

        .health-label-text h3 {
            font-size: 16px;
            margin-bottom: 2px;
        }

        .health-label-text p {
            font-size: 13px;
            color: var(--text-muted);
        }

        /* Diagnostic Checklist styling */
        .diagnostic-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .diag-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: rgba(255, 255, 255, 0.02);
            border-radius: 10px;
            padding: 12px 16px;
            border: 1px solid rgba(255, 255, 255, 0.03);
            font-size: 14px;
        }

        .diag-item-left {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }

        .diag-item-name {
            font-weight: 600;
            color: var(--text-bright);
        }

        .diag-item-msg {
            font-size: 12px;
            color: var(--text-muted);
        }

        .status-badge {
            font-family: var(--font-display);
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            padding: 4px 10px;
            border-radius: 20px;
            display: inline-block;
            letter-spacing: 0.5px;
        }

        .status-ok {
            background-color: var(--color-success-glow);
            color: var(--color-success);
            border: 1px solid rgba(0, 230, 118, 0.2);
        }

        .status-warn {
            background-color: var(--color-warning-glow);
            color: var(--color-warning);
            border: 1px solid rgba(255, 215, 0, 0.2);
        }

        .status-error {
            background-color: var(--color-error-glow);
            color: var(--color-error);
            border: 1px solid rgba(255, 82, 82, 0.2);
        }

        /* Custom buttons styling */
        .btn {
            font-family: var(--font-display);
            font-size: 13px;
            font-weight: 600;
            padding: 10px 18px;
            border-radius: 10px;
            cursor: pointer;
            border: none;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            transition: var(--transition-smooth);
            text-decoration: none;
        }

        .btn-primary {
            background: linear-gradient(135deg, var(--color-primary), #00b0ff);
            color: var(--bg-base);
            box-shadow: 0 4px 15px rgba(0, 229, 255, 0.2);
        }

        .btn-primary:hover {
            transform: translateY(-1px);
            box-shadow: 0 6px 20px rgba(0, 229, 255, 0.35);
        }

        .btn-secondary {
            background-color: rgba(255, 255, 255, 0.05);
            color: var(--text-bright);
            border: 1px solid rgba(255, 255, 255, 0.08);
        }

        .btn-secondary:hover {
            background-color: rgba(255, 255, 255, 0.09);
            border-color: rgba(255, 255, 255, 0.15);
        }

        .btn-success {
            background: rgba(0, 230, 118, 0.1);
            color: var(--color-success);
            border: 1px solid rgba(0, 230, 118, 0.25);
        }

        .btn-success:hover {
            background: rgba(0, 230, 118, 0.16);
            border-color: var(--color-success);
            box-shadow: 0 0 10px var(--color-success-glow);
        }

        .btn-icon {
            font-size: 16px;
        }

        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none !important;
            box-shadow: none !important;
        }

        /* Index grid styling */
        .indexes-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
            gap: 12px;
            margin-bottom: 20px;
        }

        .index-stat-card {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.03);
            border-radius: 12px;
            padding: 14px;
            text-align: center;
            transition: var(--transition-smooth);
        }

        .index-stat-card.active {
            border-color: var(--color-primary-glow);
            background: rgba(0, 229, 255, 0.01);
        }

        .index-stat-name {
            font-size: 11px;
            color: var(--text-muted);
            margin-bottom: 6px;
            font-weight: 500;
        }

        .index-stat-size {
            font-family: var(--font-display);
            font-size: 15px;
            font-weight: 700;
            color: var(--text-bright);
        }

        .index-stat-card.missing .index-stat-size {
            color: var(--text-muted);
            font-size: 13px;
            font-weight: 500;
        }

        /* Memory Section styling */
        .memory-section {
            grid-column: span 2;
        }

        @media (max-width: 968px) {
            .memory-section {
                grid-column: span 1;
            }
        }

        .memory-header-actions {
            display: flex;
            gap: 12px;
            align-items: center;
        }

        .search-input-wrapper {
            position: relative;
            display: flex;
            align-items: center;
        }

        .search-input {
            background-color: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 10px;
            padding: 10px 16px;
            color: var(--text-bright);
            font-size: 13px;
            outline: none;
            width: 250px;
            transition: var(--transition-smooth);
        }

        .search-input:focus {
            border-color: var(--color-primary);
            background-color: rgba(255, 255, 255, 0.06);
            box-shadow: 0 0 10px var(--color-primary-glow);
        }

        .memory-table-container {
            border: 1px solid var(--border-card);
            border-radius: 12px;
            overflow: hidden;
            background-color: rgba(255, 255, 255, 0.01);
            margin-top: 10px;
        }

        .memory-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            text-align: left;
        }

        .memory-table th, .memory-table td {
            padding: 12px 16px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
        }

        .memory-table th {
            background-color: rgba(255, 255, 255, 0.02);
            color: var(--text-bright);
            font-family: var(--font-display);
            font-weight: 600;
        }

        .memory-table tbody tr:hover {
            background-color: rgba(255, 255, 255, 0.02);
        }

        .memory-key {
            font-family: var(--font-mono);
            color: var(--color-primary);
            font-weight: 500;
            width: 20%;
        }

        .memory-value {
            color: var(--text-main);
            width: 55%;
            word-break: break-all;
        }

        .memory-tags {
            width: 15%;
        }

        .memory-tag {
            display: inline-block;
            font-size: 10px;
            background-color: rgba(255, 255, 255, 0.06);
            color: var(--text-muted);
            padding: 2px 6px;
            border-radius: 4px;
            margin-right: 4px;
            font-family: var(--font-mono);
        }

        .memory-actions {
            width: 10%;
            text-align: right;
        }

        .action-delete-btn {
            background: transparent;
            border: none;
            color: var(--color-error);
            cursor: pointer;
            padding: 4px 8px;
            border-radius: 6px;
            transition: var(--transition-smooth);
            font-size: 12px;
        }

        .action-delete-btn:hover {
            background-color: var(--color-error-glow);
        }

        .empty-state {
            text-align: center;
            padding: 40px;
            color: var(--text-muted);
        }

        /* Project Pack Section styling */
        .packs-container {
            display: grid;
            grid-template-columns: 1fr;
            gap: 20px;
            margin-top: 15px;
        }

        .pack-card {
            background: rgba(23, 29, 43, 0.4);
            border: 1px solid var(--border-card);
            border-radius: 16px;
            padding: 24px;
            display: grid;
            grid-template-columns: 1.2fr 1.8fr;
            gap: 24px;
            backdrop-filter: blur(12px);
            transition: var(--transition-smooth);
        }

        @media (max-width: 768px) {
            .pack-card {
                grid-template-columns: 1fr;
            }
        }

        .pack-card:hover {
            border-color: var(--border-card-hover);
            background: rgba(23, 29, 43, 0.6);
        }

        .pack-meta-section {
            display: flex;
            flex-direction: column;
            gap: 12px;
            justify-content: space-between;
        }

        .pack-details-section {
            display: flex;
            flex-direction: column;
            gap: 16px;
            border-left: 1px solid rgba(255, 255, 255, 0.05);
            padding-left: 24px;
        }

        @media (max-width: 768px) {
            .pack-details-section {
                border-left: none;
                padding-left: 0;
                border-top: 1px solid rgba(255, 255, 255, 0.05);
                padding-top: 16px;
            }
        }

        .pack-card-top h3 {
            font-size: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
            font-family: var(--font-display);
            color: var(--text-bright);
        }

        .pack-py-badge {
            font-family: var(--font-mono);
            font-size: 11px;
            font-weight: 600;
            background: rgba(0, 229, 255, 0.1);
            color: var(--color-primary);
            padding: 2px 8px;
            border-radius: 6px;
            border: 1px solid rgba(0, 229, 255, 0.2);
            width: fit-content;
        }

        .pack-card-desc {
            font-size: 13px;
            color: var(--text-muted);
            line-height: 1.5;
        }

        .pkg-list-container {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }

        .pkg-item {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 8px;
            padding: 4px 10px;
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 12px;
            color: var(--text-main);
            transition: var(--transition-smooth);
        }

        .pkg-item:hover {
            border-color: rgba(255, 82, 82, 0.4);
            background: rgba(255, 82, 82, 0.05);
        }

        .pkg-remove-btn {
            background: transparent;
            border: none;
            color: var(--color-error);
            font-weight: bold;
            cursor: pointer;
            font-size: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            width: 14px;
            height: 14px;
            border-radius: 50%;
            transition: var(--transition-smooth);
        }

        .pkg-remove-btn:hover {
            background: rgba(255, 82, 82, 0.2);
        }

        .wheels-list-container {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            max-height: 100px;
            overflow-y: auto;
            background: rgba(0, 0, 0, 0.15);
            padding: 8px;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.03);
        }

        .wheel-badge {
            font-family: var(--font-mono);
            font-size: 10px;
            background: rgba(0, 230, 118, 0.05);
            color: var(--color-success);
            border: 1px solid rgba(0, 230, 118, 0.15);
            padding: 1px 6px;
            border-radius: 4px;
            max-width: 250px;
            text-overflow: ellipsis;
            white-space: nowrap;
            overflow: hidden;
        }

        .pack-actions-bar {
            display: flex;
            gap: 12px;
            margin-top: 12px;
        }

        /* CLI Terminal logs wrapper */
        .terminal-log-wrapper {
            grid-column: span 2;
        }

        @media (max-width: 968px) {
            .terminal-log-wrapper {
                grid-column: span 1;
            }
        }

        .terminal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #141824;
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-bottom: none;
            padding: 10px 18px;
            border-top-left-radius: 12px;
            border-top-right-radius: 12px;
        }

        .terminal-header-left {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .terminal-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }

        .dot-red { background-color: #ff5f56; }
        .dot-yellow { background-color: #ffbd2e; }
        .dot-green { background-color: #27c93f; }

        .terminal-title {
            font-family: var(--font-mono);
            font-size: 12px;
            color: var(--text-muted);
            margin-left: 8px;
        }

        .terminal-body {
            background-color: #0b0d16;
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-bottom-left-radius: 12px;
            border-bottom-right-radius: 12px;
            padding: 16px;
            font-family: var(--font-mono);
            font-size: 12px;
            color: #d1d5db;
            height: 200px;
            overflow-y: auto;
            white-space: pre-wrap;
            box-shadow: inset 0 4px 10px rgba(0,0,0,0.5);
        }

        .terminal-line {
            margin-bottom: 4px;
        }

        .terminal-line.info { color: #60a5fa; }
        .terminal-line.success { color: #34d399; }
        .terminal-line.warning { color: #fbbf24; }
        .terminal-line.error { color: #f87171; }

        /* Dialog / Popup Modal styling */
        .modal {
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background: rgba(6, 8, 12, 0.85);
            backdrop-filter: blur(8px);
            z-index: 1000;
            display: flex;
            align-items: center;
            justify-content: center;
            opacity: 0;
            pointer-events: none;
            transition: var(--transition-smooth);
        }

        .modal.active {
            opacity: 1;
            pointer-events: auto;
        }

        .modal-card {
            background: var(--bg-surface);
            border: 1px solid var(--border-card-hover);
            border-radius: 16px;
            width: 500px;
            max-width: 90%;
            padding: 24px;
            box-shadow: 0 20px 50px rgba(0, 229, 255, 0.15);
            transform: translateY(20px);
            transition: var(--transition-smooth);
        }

        .modal.active .modal-card {
            transform: translateY(0);
        }

        .modal-title {
            font-size: 20px;
            margin-bottom: 16px;
        }

        .form-group {
            margin-bottom: 16px;
        }

        .form-group label {
            display: block;
            font-size: 12px;
            color: var(--text-muted);
            margin-bottom: 6px;
            font-weight: 500;
        }

        .form-input {
            width: 100%;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
            padding: 10px 14px;
            color: var(--text-bright);
            font-size: 13px;
            outline: none;
            transition: var(--transition-smooth);
        }

        .form-input:focus {
            border-color: var(--color-primary);
            box-shadow: 0 0 8px var(--color-primary-glow);
        }

        .form-actions {
            display: flex;
            justify-content: flex-end;
            gap: 12px;
            margin-top: 24px;
        }

        /* Pulsing Glow Animation */
        @keyframes pulse-glow {
            0% { box-shadow: 0 0 10px var(--color-primary-glow); }
            50% { box-shadow: 0 0 25px rgba(0, 229, 255, 0.35); }
            100% { box-shadow: 0 0 10px var(--color-primary-glow); }
        }

        .indexing-active {
            animation: pulse-glow 2s infinite;
            border-color: var(--color-primary);
        }

        /* Rotating spinner */
        .spinner {
            width: 16px;
            height: 16px;
            border: 2px solid rgba(255, 255, 255, 0.1);
            border-top: 2px solid currentColor;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            display: inline-block;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        /* Subagents Console styling */
        .subagents-section {
            grid-column: span 2;
        }

        .subagents-launcher-bar {
            display: flex;
            gap: 12px;
            align-items: center;
            background: rgba(255, 255, 255, 0.01);
            border: 1px solid rgba(255, 255, 255, 0.04);
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 20px;
        }

        .subagents-list {
            display: flex;
            flex-direction: column;
            gap: 16px;
        }

        .subagent-item-card {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.04);
            border-radius: 12px;
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            transition: var(--transition-smooth);
        }

        .subagent-item-card:hover {
            border-color: rgba(0, 229, 255, 0.2);
            background: rgba(255, 255, 255, 0.03);
        }

        .subagent-item-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .subagent-item-meta {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .subagent-cmd-text {
            font-family: var(--font-mono);
            font-size: 13px;
            color: var(--color-primary);
            font-weight: 500;
        }

        .subagent-badge {
            font-size: 10px;
            font-weight: 600;
            padding: 2px 8px;
            border-radius: 20px;
            text-transform: uppercase;
        }

        .subagent-badge.running {
            background: rgba(0, 229, 255, 0.1);
            color: var(--color-primary);
            border: 1px solid rgba(0, 229, 255, 0.2);
            animation: pulse-glow 2s infinite;
        }

        .subagent-badge.completed {
            background: rgba(0, 230, 118, 0.1);
            color: var(--color-success);
            border: 1px solid rgba(0, 230, 118, 0.2);
        }

        .subagent-badge.failed {
            background: rgba(255, 82, 82, 0.1);
            color: var(--color-error);
            border: 1px solid rgba(255, 82, 82, 0.2);
        }

        .subagent-badge.killed {
            background: rgba(255, 215, 0, 0.1);
            color: var(--color-warning);
            border: 1px solid rgba(255, 215, 0, 0.2);
        }

        .subagent-terminal {
            background: #06080c;
            border: 1px solid rgba(255, 255, 255, 0.04);
            border-radius: 8px;
            padding: 12px;
            height: 150px;
            overflow-y: auto;
            font-family: var(--font-mono);
            font-size: 11px;
            color: #d1d5db;
            white-space: pre-wrap;
            box-shadow: inset 0 2px 8px rgba(0,0,0,0.8);
        }

        /* Dependency Graph Styles */
        .graph-container {
            max-height: 400px;
            overflow-y: auto;
            background: rgba(0,0,0,0.2);
            border: 1px solid rgba(255,255,255,0.04);
            border-radius: 12px;
            padding: 16px;
            font-family: var(--font-sans);
        }
        .graph-tree-node {
            margin-left: 16px;
            border-left: 1px dashed rgba(255,255,255,0.1);
            padding-left: 12px;
            margin-top: 4px;
        }
        .graph-file-item {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 4px 8px;
            border-radius: 6px;
            cursor: pointer;
            transition: var(--transition-smooth);
            font-size: 13px;
        }
        .graph-file-item:hover {
            background: rgba(255, 255, 255, 0.04);
        }
        .graph-badge-lang {
            font-size: 10px;
            padding: 1px 6px;
            border-radius: 4px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .graph-badge-lang.python { background: rgba(53, 114, 165, 0.2); color: #3572A5; }
        .graph-badge-lang.javascript { background: rgba(241, 224, 90, 0.2); color: #F1E05A; }
        .graph-badge-lang.typescript { background: rgba(43, 116, 137, 0.2); color: #2B7489; }
        
        /* Preemptive Health Monitor Styles */
        .health-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
            margin-bottom: 16px;
        }
        .health-stat-card {
            background: rgba(255,255,255,0.02);
            border: 1px solid rgba(255,255,255,0.04);
            border-radius: 8px;
            padding: 12px;
            text-align: center;
        }
        .health-stat-val {
            font-size: 20px;
            font-weight: 700;
            color: var(--text-bright);
            margin-top: 4px;
        }
        .health-stat-label {
            font-size: 11px;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .health-errors-list {
            max-height: 180px;
            overflow-y: auto;
            margin-bottom: 16px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .health-error-item {
            background: rgba(255, 82, 82, 0.05);
            border: 1px solid rgba(255, 82, 82, 0.15);
            border-radius: 8px;
            padding: 10px 14px;
            font-size: 12px;
        }
        .health-error-title {
            color: var(--color-error);
            font-weight: 600;
            margin-bottom: 4px;
        }
        .health-warnings-list {
            max-height: 180px;
            overflow-y: auto;
            margin-bottom: 16px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .health-warning-item {
            background: rgba(255, 215, 0, 0.05);
            border: 1px solid rgba(255, 215, 0, 0.15);
            border-radius: 8px;
            padding: 10px 14px;
            font-size: 12px;
        }
        .health-warning-title {
            color: var(--color-warning);
            font-weight: 600;
            margin-bottom: 4px;
        }

        /* Audit Ledger Styles */
        .ledger-timeline {
            max-height: 400px;
            overflow-y: auto;
            background: rgba(0,0,0,0.2);
            border: 1px solid rgba(255,255,255,0.04);
            border-radius: 12px;
            padding: 16px;
            position: relative;
        }
        .ledger-item {
            position: relative;
            padding-left: 24px;
            margin-bottom: 20px;
        }
        .ledger-item::before {
            content: '';
            position: absolute;
            left: 0;
            top: 4px;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--color-primary);
            box-shadow: 0 0 8px var(--color-primary);
        }
        .ledger-item::after {
            content: '';
            position: absolute;
            left: 3px;
            top: 12px;
            width: 2px;
            height: calc(100% + 8px);
            background: rgba(255,255,255,0.05);
        }
        .ledger-item:last-child::after {
            display: none;
        }
        .ledger-meta {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 11px;
            color: var(--text-muted);
            margin-bottom: 4px;
        }
        .ledger-tool {
            font-family: var(--font-mono);
            font-size: 13px;
            font-weight: 600;
            color: var(--text-bright);
        }
        .ledger-summary {
            font-size: 13px;
            color: #d1d5db;
        }
        .ledger-args {
            font-family: var(--font-mono);
            font-size: 11px;
            background: rgba(0,0,0,0.3);
            padding: 4px 8px;
            border-radius: 4px;
            margin-top: 6px;
            word-break: break-all;
            color: var(--text-muted);
        }
        .ledger-badge {
            font-size: 10px;
            padding: 1px 6px;
            border-radius: 4px;
            font-weight: 600;
        }
        .ledger-badge.success { background: rgba(0, 230, 118, 0.1); color: var(--color-success); }
        .ledger-badge.failed { background: rgba(255, 82, 82, 0.1); color: var(--color-error); }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <header>
            <div class="header-title-section">
                <div class="header-logo">G</div>
                <div class="header-text">
                    <h1>MCP Global Dashboard</h1>
                    <p id="system-path">Project Root: Loading...</p>
                </div>
            </div>
            <div>
                <button class="btn btn-secondary" onclick="runDiagnostics()"><span class="btn-icon">↺</span> Reload Status</button>
            </div>
        </header>

        <div class="grid-dashboard">
            <!-- Diagnostics / Doctor -->
            <div class="card" id="doctor-card">
                <div class="card-title-bar">
                    <h2><span class="btn-icon" style="color:var(--color-primary)">🩺</span> System Health (Doctor)</h2>
                    <button class="btn btn-success btn-icon" id="btn-fix" onclick="runSelfRepair()" style="display:none">🔧 Run Self-Repair</button>
                </div>

                <div class="health-circle-container">
                    <div class="health-circle" id="health-circle-glow">
                        <span class="health-score-val" id="health-score">--</span>
                    </div>
                    <div class="health-label-text">
                        <h3 id="health-verdict">Running Diagnostics...</h3>
                        <p id="health-issues-desc">Checking environment components.</p>
                    </div>
                </div>

                <div class="diagnostic-list" id="diagnostic-feed">
                    <div style="text-align:center; padding: 20px; color: var(--text-muted)">Loading diagnostics...</div>
                </div>
            </div>

            <!-- Indexes panel -->
            <div class="card" id="indexes-card">
                <div class="card-title-bar">
                    <h2><span class="btn-icon" style="color:var(--color-primary)">📊</span> Codebase Intelligence</h2>
                    <div style="display:flex; gap: 8px;">
                        <button class="btn btn-secondary" id="btn-index-incremental" onclick="triggerIndexing(false)">Incremental Index</button>
                        <button class="btn btn-primary" id="btn-index-full" onclick="triggerIndexing(true)">Full Re-Index</button>
                    </div>
                </div>

                <div style="font-size: 13px; color: var(--text-muted); margin-bottom: 20px;">
                    Integrates vector embedding semantic store, TODO scanner, configuration variables, impact dependencies, git commit history, and automated docstring statuses.
                </div>

                <div class="indexes-grid" id="indexes-stat-grid">
                    <!-- Stat cards -->
                </div>
                
                <div style="background: rgba(255,255,255,0.01); border: 1px solid rgba(255,255,255,0.03); padding: 14px; border-radius: 10px; font-size: 13px; display:flex; justify-content:space-between; align-items:center;">
                    <span style="color: var(--text-muted)">Indexing Status:</span>
                    <span id="indexing-status-text" style="font-weight:600; color:var(--text-bright)">Idle</span>
                </div>
            </div>

            <!-- Project Packs -->
            <div class="card" style="grid-column: span 2;" id="packs-card">
                <div class="card-title-bar">
                    <h2><span class="btn-icon" style="color:var(--color-success)">📦</span> Project Packs Manager</h2>
                    <button class="btn btn-primary" onclick="openCreatePackModal()">+ Create Custom Pack</button>
                </div>
                <div style="font-size: 13px; color: var(--text-muted); margin-bottom: 16px;">
                    Project Packs enable automatic local configuration setups including specialized virtual environment libraries, pre-built binary dependencies, and automation setups tailored directly to your codebase architecture.
                </div>
                <div class="packs-container" id="packs-feed">
                    <div style="grid-column:span 2; text-align:center; padding: 20px; color:var(--text-muted)">Scanning packs...</div>
                </div>
            </div>

            <!-- Memory Store -->
            <div class="card memory-section">
                <div class="card-title-bar">
                    <h2><span class="btn-icon" style="color:var(--color-primary)">🧠</span> Persistent SQLite Memory Explorer</h2>
                    <div class="memory-header-actions">
                        <div class="search-input-wrapper">
                            <input type="text" class="search-input" id="memory-search" placeholder="Search key or content..." oninput="filterMemories()">
                        </div>
                        <button class="btn btn-primary" onclick="openAddMemoryModal()">+ Remember Key</button>
                    </div>
                </div>

                <div class="memory-table-container">
                    <table class="memory-table">
                        <thead>
                            <tr>
                                <th>Key / Knowledge</th>
                                <th>Details / Saved Context</th>
                                <th>Tags</th>
                                <th style="text-align: right">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="memory-feed-body">
                            <tr>
                                <td colspan="4" class="empty-state">Loading SQLite memory base...</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Subagents Console -->
            <div class="card subagents-section" style="grid-column: span 2;" id="subagents-card">
                <div class="card-title-bar">
                    <h2><span class="btn-icon" style="color:var(--color-primary)">🤖</span> Parallel Agent & Task Orchestrator</h2>
                    <div style="display:flex; align-items:center; gap:12px;">
                        <span id="watcher-badge" class="status-badge" style="background:rgba(0, 229, 255, 0.1); color:var(--color-primary)">Watcher: Active (Idle)</span>
                    </div>
                </div>
                
                <div style="font-size: 13px; color: var(--text-muted); margin-bottom: 20px;">
                    Spawn and monitor concurrent subagent processes in the background. Stream real-time standard output and terminate long-running processes directly from this console.
                </div>

                <div class="subagents-launcher-bar">
                    <div style="flex: 1; display: flex; gap: 12px; align-items: center;">
                        <select class="search-input" id="subagent-preset-cmd" onchange="onPresetCmdChange()" style="width: 280px; background-color: rgba(18,22,32,0.9); border:1px solid rgba(255,255,255,0.08);">
                            <option value="">-- Choose Preset Task or Custom --</option>
                            <option value="python mcp-agentic-rules/mcp.py review src/">Code Review (mcp review)</option>
                            <option value="python mcp-agentic-rules/mcp.py security src/">Security Audit (mcp security)</option>
                            <option value="python mcp-agentic-rules/mcp.py deadcode src/">Dead Code Analysis (mcp deadcode)</option>
                            <option value="python mcp-agentic-rules/mcp.py coverage src/">Docstring Coverage Check</option>
                            <option value="python mcp-agentic-rules/mcp.py profile src/">Complexity Profiling</option>
                            <option value="custom">Custom Command Input...</option>
                        </select>
                        <input type="text" class="search-input" id="subagent-custom-cmd" placeholder="e.g. python mcp-agentic-rules/mcp.py review src/" style="flex: 1; display: none;">
                    </div>
                    <button class="btn btn-primary" onclick="spawnSubagent()">+ Launch Agent</button>
                </div>

                <div class="subagents-list" id="subagents-feed">
                    <div class="empty-state">No background subagent processes launched yet.</div>
                </div>
            </div>

            <!-- Preemptive Health Monitor Card -->
            <div class="card" id="preemptive-health-card">
                <div class="card-title-bar">
                    <h2><span class="btn-icon" style="color:var(--color-primary)">&#x1F6E1;</span> Preemptive Health Monitor</h2>
                    <span id="daemon-badge" class="status-badge" style="background:rgba(0, 229, 255, 0.1); color:var(--color-primary)">Daemon: Initializing</span>
                </div>
                <div style="font-size: 13px; color: var(--text-muted); margin-bottom: 20px;">
                    Idle-triggered active unit testing and syntax compilation daemon. Reports real-time structural bugs and tests downstream ripple impacts.
                </div>
                <div class="health-grid">
                    <div class="health-stat-card">
                        <div class="health-stat-label">Syntax Errors</div>
                        <div class="health-stat-val" id="health-stat-syntax" style="color: var(--color-success)">0</div>
                    </div>
                    <div class="health-stat-card">
                        <div class="health-stat-label">Tests Passed</div>
                        <div class="health-stat-val" id="health-stat-passed" style="color: var(--color-success)">0</div>
                    </div>
                    <div class="health-stat-card">
                        <div class="health-stat-label">Tests Failed</div>
                        <div class="health-stat-val" id="health-stat-failed" style="color: var(--color-success)">0</div>
                    </div>
                </div>
                <div class="health-errors-list" id="health-errors-container" style="display:none">
                    <!-- Syntax Errors -->
                </div>
                <div class="health-warnings-list" id="health-warnings-container" style="display:none">
                    <!-- Ripple Warnings -->
                </div>
                <div style="background: rgba(255,255,255,0.01); border: 1px solid rgba(255,255,255,0.03); padding: 14px; border-radius: 10px; font-size: 13px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                        <span style="color: var(--text-muted)">Last Checked:</span>
                        <span id="daemon-last-checked" style="font-weight:600; color:var(--text-bright)">--</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="color: var(--text-muted)">Test Status:</span>
                        <span id="daemon-test-status" style="font-weight:600; color:var(--color-success)">Healthy</span>
                    </div>
                </div>
            </div>

            <!-- Codebase Dependency Graph Card -->
            <div class="card" id="dependency-graph-card">
                <div class="card-title-bar">
                    <h2><span class="btn-icon" style="color:var(--color-primary)">&#x1F578;</span> Dependency &amp; Inheritance Graph</h2>
                    <button class="btn btn-secondary btn-icon" onclick="reloadDependencyGraph()">↺ Reload</button>
                </div>
                <div style="font-size: 13px; color: var(--text-muted); margin-bottom: 20px;">
                    Macro codebase topological layout. Traces imported modules, inheritance trees, and ripple-impact paths.
                </div>
                <div class="graph-container" id="graph-feed-container">
                    <div class="empty-state">Loading codebase dependency graph...</div>
                </div>
            </div>

            <!-- Audit Ledger Card -->
            <div class="card" style="grid-column: span 2;" id="audit-ledger-card">
                <div class="card-title-bar">
                    <h2><span class="btn-icon" style="color:var(--color-primary)">&#x1F4DC;</span> Vectorized Agent Action &amp; Audit Ledger</h2>
                    <button class="btn btn-secondary btn-icon" onclick="reloadAuditLedger()">↺ Reload</button>
                </div>
                <div style="font-size: 13px; color: var(--text-muted); margin-bottom: 20px;">
                    SQLite-persisted action stream. Vectorizes tool calls, prompt decisions, shell executions, and compiles downstream side-effects.
                </div>
                <div class="ledger-timeline" id="ledger-feed-container">
                    <div class="empty-state">No agent actions recorded yet.</div>
                </div>
            </div>

            <!-- Output Logs -->
            <div class="terminal-log-wrapper">
                <div class="terminal-header">
                    <div class="terminal-header-left">
                        <div class="terminal-dot dot-red"></div>
                        <div class="terminal-dot dot-yellow"></div>
                        <div class="terminal-dot dot-green"></div>
                        <span class="terminal-title">System Log Terminal</span>
                    </div>
                    <div id="operation-badge" class="status-badge" style="display:none; background:rgba(255,255,255,0.05); color:var(--text-muted)">Idle</div>
                </div>
                <div class="terminal-body" id="terminal-body-feed">
[SYSTEM] Local GUI Dashboard initialized.
[SYSTEM] Binding sockets, waiting for diagnostics trigger...
                </div>
            </div>
        </div>
    </div>

    <!-- Modal Form -->
    <div class="modal" id="add-memory-modal">
        <div class="modal-card">
            <h3 class="modal-title">Remember Knowledge</h3>
            <div class="form-group">
                <label for="mem-key">Key / Subject</label>
                <input type="text" class="form-input" id="mem-key" placeholder="e.g. auth_handler">
            </div>
            <div class="form-group">
                <label for="mem-val">Value / Details</label>
                <textarea class="form-input" id="mem-val" rows="4" style="resize:none" placeholder="Enter context or instructions for agents..."></textarea>
            </div>
            <div class="form-group">
                <label for="mem-tags">Tags (comma separated)</label>
                <input type="text" class="form-input" id="mem-tags" placeholder="e.g. auth, api, helper">
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="closeAddMemoryModal()">Cancel</button>
                <button class="btn btn-primary" onclick="submitNewMemory()">Save Memory</button>
            </div>
        </div>
    </div>

    <!-- Modal Pack Form -->
    <div class="modal" id="create-pack-modal">
        <div class="modal-card">
            <h3 class="modal-title">Create Custom Project Pack</h3>
            <div class="form-group">
                <label for="new-pack-name">Pack Folder Name</label>
                <input type="text" class="form-input" id="new-pack-name" placeholder="e.g. Fullstack_Web_Development">
            </div>
            <div class="form-group">
                <label for="new-pack-py">Required Python Version</label>
                <input type="text" class="form-input" id="new-pack-py" value="3.11" placeholder="e.g. 3.11 or 3.12">
            </div>
            <div class="form-group">
                <label for="new-pack-desc">Pack Description</label>
                <textarea class="form-input" id="new-pack-desc" rows="3" style="resize:none" placeholder="Provide a premium context summary for this pack..."></textarea>
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="closeCreatePackModal()">Cancel</button>
                <button class="btn btn-primary" onclick="submitNewPack()">Create Pack</button>
            </div>
        </div>
    </div>

    <script>
        let allMemories = [];
        let isPollingIndex = false;

        // Terminal Logging helper
        function log(message, type = 'info') {
            const feed = document.getElementById('terminal-body-feed');
            const prefix = `[${new Date().toLocaleTimeString()}]`;
            
            const line = document.createElement('div');
            line.className = `terminal-line ${type}`;
            line.textContent = `${prefix} ${message}`;
            
            feed.appendChild(line);
            feed.scrollTop = feed.scrollHeight;
        }

        // Fetch Diagnostics (Doctor)
        async function runDiagnostics() {
            log("Triggering diagnostic checks...", 'info');
            try {
                const res = await fetch('/api/doctor');
                const data = await res.json();
                
                // Set path
                document.getElementById('system-path').textContent = `Project Root: ${data.root}`;
                
                // Score
                const score = data.health_score;
                document.getElementById('health-score').textContent = `${score}%`;
                
                const circle = document.getElementById('health-circle-glow');
                const deg = (score / 100) * 360;
                circle.style.setProperty('--health-deg', `${deg}deg`);
                
                // Color mapping
                if (score >= 90) {
                    circle.style.borderColor = 'var(--color-success)';
                    document.getElementById('health-verdict').textContent = "Systems Operational";
                    document.getElementById('health-verdict').style.color = 'var(--color-success)';
                } else if (score >= 60) {
                    circle.style.borderColor = 'var(--color-warning)';
                    document.getElementById('health-verdict').textContent = "Warnings Detected";
                    document.getElementById('health-verdict').style.color = 'var(--color-warning)';
                } else {
                    circle.style.borderColor = 'var(--color-error)';
                    document.getElementById('health-verdict').textContent = "System Health Alert";
                    document.getElementById('health-verdict').style.color = 'var(--color-error)';
                }

                // Description
                const issuesCount = data.issues.length;
                document.getElementById('health-issues-desc').textContent = 
                    issuesCount === 0 ? "No issues detected. Dashboard is healthy." : `${issuesCount} issue(s) require attention.`;

                // Fix Button
                const btnFix = document.getElementById('btn-fix');
                const hasFixable = data.issues.some(i => i.type === 'git_hooks' || i.type.startsWith('index'));
                btnFix.style.display = hasFixable ? 'inline-flex' : 'none';

                // Diagnostic Feed
                const feed = document.getElementById('diagnostic-feed');
                feed.innerHTML = '';
                
                data.diagnostics.forEach(diag => {
                    const item = document.createElement('div');
                    item.className = 'diag-item';
                    
                    const badgeClass = `status-badge status-${diag.status}`;
                    
                    item.innerHTML = `
                        <div class="diag-item-left">
                            <span class="diag-item-name">${diag.name}</span>
                            <span class="diag-item-msg">${diag.message}</span>
                        </div>
                        <span class="${badgeClass}">${diag.status}</span>
                    `;
                    feed.appendChild(diag.name === 'Codebase Indexes' ? renderIndexStats(diag) : item);
                });

                log(`Diagnostics loaded. Health score: ${score}/100.`, score >= 90 ? 'success' : score >= 60 ? 'warning' : 'error');
            } catch (err) {
                log(`Failed to load diagnostics: ${err.message}`, 'error');
            }
        }

        // Render Codebase Indexes inside the diag feed
        function renderIndexStats(diag) {
            const wrapper = document.createElement('div');
            wrapper.style.display = 'contents';
            
            // Render basic item
            const item = document.createElement('div');
            item.className = 'diag-item';
            item.innerHTML = `
                <div class="diag-item-left">
                    <span class="diag-item-name">${diag.name}</span>
                    <span class="diag-item-msg">${diag.message}</span>
                </div>
                <span class="status-badge status-${diag.status}">${diag.status}</span>
            `;
            wrapper.appendChild(item);

            // Populate global stats cards
            const grid = document.getElementById('indexes-stat-grid');
            grid.innerHTML = '';
            
            if (diag.details && diag.details.indexed) {
                const individual = diag.details.individual_indexes;
                for (const [name, info] of Object.entries(individual)) {
                    const card = document.createElement('div');
                    card.className = `index-stat-card ${info.exists ? 'active' : 'missing'}`;
                    
                    const sizeStr = info.exists ? formatBytes(info.size_bytes) : 'Missing';
                    
                    card.innerHTML = `
                        <div class="index-stat-name">${name}</div>
                        <div class="index-stat-size">${sizeStr}</div>
                    `;
                    grid.appendChild(card);
                }
            }
            
            return item;
        }

        function formatBytes(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
        }

        // Run Fix Repair
        async function runSelfRepair() {
            log("Starting automatic self-repair process...", 'warning');
            const btn = document.getElementById('btn-fix');
            btn.disabled = true;
            btn.innerHTML = `<span class="spinner"></span> Repairing...`;

            try {
                const res = await fetch('/api/doctor/fix', { method: 'POST' });
                const result = await res.json();
                
                if (result.success) {
                    log("Self-repair completed successfully!", 'success');
                    result.fixes.forEach(fix => log(`REPAIR: ${fix}`, 'success'));
                } else {
                    log(`Self-repair encountered warnings or errors: ${result.error}`, 'error');
                }
                
                await runDiagnostics();
            } catch (err) {
                log(`Failed to run self-repair: ${err.message}`, 'error');
            } finally {
                btn.disabled = false;
                btn.innerHTML = `🔧 Run Self-Repair`;
            }
        }

        // Trigger Indexing
        async function triggerIndexing(full = false) {
            const btnFull = document.getElementById('btn-index-full');
            const btnIncr = document.getElementById('btn-index-incremental');
            const statusCard = document.getElementById('indexes-card');
            
            log(`Starting codebase indexing (Mode: ${full ? 'Full' : 'Incremental'})...`, 'warning');
            
            btnFull.disabled = true;
            btnIncr.disabled = true;
            statusCard.classList.add('indexing-active');
            
            document.getElementById('indexing-status-text').innerHTML = `<span class="spinner"></span> Running index build...`;

            try {
                const res = await fetch('/api/index/all', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ full })
                });
                
                const data = await res.json();
                log(`Index runner spawned: ${data.message}`, 'info');
                
                // Start polling status
                isPollingIndex = true;
                pollIndexingStatus();
            } catch (err) {
                log(`Failed to run index build: ${err.message}`, 'error');
                btnFull.disabled = false;
                btnIncr.disabled = false;
                statusCard.classList.remove('indexing-active');
                document.getElementById('indexing-status-text').textContent = 'Error';
            }
        }

        // Poll Index Status
        async function pollIndexingStatus() {
            if (!isPollingIndex) return;

            try {
                const res = await fetch('/api/index/status');
                const data = await res.json();
                
                document.getElementById('indexing-status-text').innerHTML = `<span class="spinner"></span> ${data.status}`;
                
                if (data.logs && data.logs.length > 0) {
                    data.logs.forEach(line => {
                        if (line.includes('[INFO]')) log(line.replace('[INFO] ', ''), 'info');
                        else if (line.includes('[OK]')) log(line.replace('[OK] ', ''), 'success');
                        else if (line.includes('[WARNING]')) log(line.replace('[WARNING] ', ''), 'warning');
                        else if (line.includes('[FAIL]')) log(line.replace('[FAIL] ', ''), 'error');
                    });
                }

                if (data.status === 'Complete') {
                    log("Indexing completed successfully!", 'success');
                    isPollingIndex = false;
                    cleanupIndexingUI();
                    runDiagnostics();
                } else if (data.status === 'Failed' || data.status === 'Idle') {
                    if (data.status === 'Failed') log("Indexing build failed. Check terminal logs.", 'error');
                    isPollingIndex = false;
                    cleanupIndexingUI();
                } else {
                    // Poll again
                    setTimeout(pollIndexingStatus, 2000);
                }
            } catch (err) {
                isPollingIndex = false;
                cleanupIndexingUI();
            }
        }

        function cleanupIndexingUI() {
            document.getElementById('btn-index-full').disabled = false;
            document.getElementById('btn-index-incremental').disabled = false;
            document.getElementById('indexes-card').classList.remove('indexing-active');
            document.getElementById('indexing-status-text').textContent = 'Idle';
        }

        // Fetch Memories
        async function loadMemories() {
            try {
                const res = await fetch('/api/memory/list');
                allMemories = await res.json();
                renderMemories(allMemories);
            } catch (err) {
                log(`Failed to load SQLite memory base: ${err.message}`, 'error');
            }
        }

        // Render Memories in Table
        function renderMemories(memories) {
            const body = document.getElementById('memory-feed-body');
            body.innerHTML = '';

            if (memories.length === 0) {
                body.innerHTML = `
                    <tr>
                        <td colspan="4" class="empty-state">No matching memory records found.</td>
                    </tr>
                `;
                return;
            }

            memories.forEach(mem => {
                const row = document.createElement('tr');
                
                const tagsHtml = mem.tags.map(t => `<span class="memory-tag">${t}</span>`).join('');
                
                row.innerHTML = `
                    <td class="memory-key">${escapeHtml(mem.key)}</td>
                    <td class="memory-value">${escapeHtml(mem.value)}</td>
                    <td class="memory-tags">${tagsHtml}</td>
                    <td class="memory-actions">
                        <button class="action-delete-btn" onclick="deleteMemory('${escapeJs(mem.key)}')">Forget</button>
                    </td>
                `;
                body.appendChild(row);
            });
        }

        // Filter memories instantly in real-time
        function filterMemories() {
            const query = document.getElementById('memory-search').value.toLowerCase();
            const filtered = allMemories.filter(m => 
                m.key.toLowerCase().includes(query) || 
                m.value.toLowerCase().includes(query) ||
                m.tags.some(t => t.toLowerCase().includes(query))
            );
            renderMemories(filtered);
        }

        // Delete memory record
        async function deleteMemory(key) {
            if (!confirm(`Are you sure you want to delete memory key '${key}'?`)) return;
            log(`Forgetting memory key: ${key}...`, 'warning');
            
            try {
                const res = await fetch('/api/memory/forget', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key })
                });
                const result = await res.json();
                if (result.success) {
                    log(`Forgot memory key '${key}' successfully.`, 'success');
                    loadMemories();
                } else {
                    log(`Failed to delete memory: ${result.error}`, 'error');
                }
            } catch (err) {
                log(`Failed to forget memory: ${err.message}`, 'error');
            }
        }

        // Project Packs functions
        async function loadPacks() {
            try {
                const res = await fetch('/api/packs/list');
                const packs = await res.json();
                
                const feed = document.getElementById('packs-feed');
                feed.innerHTML = '';

                if (packs.length === 0) {
                    feed.innerHTML = '<div style="grid-column:span 2;" class="empty-state">No project packs found or created.</div>';
                    return;
                }

                packs.forEach(pack => {
                    const card = document.createElement('div');
                    card.className = 'pack-card';                    // Render requirements packages with caching status pills
                    let pkgListHtml = '';
                    if (pack.requirements_status && pack.requirements_status.length > 0) {
                        pkgListHtml = pack.requirements_status.map(item => {
                            const statusStyle = item.cached ? 
                                'background: rgba(46, 204, 113, 0.15); color: #2ecc71; border: 1px solid rgba(46, 204, 113, 0.3);' : 
                                'background: rgba(241, 196, 15, 0.15); color: #f1c40f; border: 1px solid rgba(241, 196, 15, 0.3);';
                            const statusLabel = item.cached ? 'Cached' : 'Missing';
                            
                            return `
                                <div class="pkg-item" style="display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; background: rgba(255,255,255,0.03); border-radius: 6px; margin-bottom: 6px; border: 1px solid rgba(255,255,255,0.05);">
                                    <div style="display: flex; align-items: center; gap: 8px;">
                                        <span style="font-weight: 500; font-size: 13px;">${escapeHtml(item.requirement)}</span>
                                        <span class="pkg-status-badge" style="font-size: 9px; padding: 1px 5px; border-radius: 12px; font-weight: bold; text-transform: uppercase; ${statusStyle}">${statusLabel}</span>
                                    </div>
                                    <button class="pkg-remove-btn" style="background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 14px; line-height: 1; padding: 2px 6px; hover: color: var(--color-error);" onclick="removePackageFromPack('${escapeJs(pack.name)}', '${escapeJs(item.requirement)}')" title="Remove Package">×</button>
                                </div>
                            `;
                        }).join('');
                    } else if (pack.requirements && pack.requirements.length > 0) {
                        // Fallback in case requirements_status is empty
                        pkgListHtml = pack.requirements.map(pkg => `
                            <div class="pkg-item" style="display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; background: rgba(255,255,255,0.03); border-radius: 6px; margin-bottom: 6px; border: 1px solid rgba(255,255,255,0.05);">
                                <span>${escapeHtml(pkg)}</span>
                                <button class="pkg-remove-btn" onclick="removePackageFromPack('${escapeJs(pack.name)}', '${escapeJs(pkg)}')" title="Remove Package">×</button>
                            </div>
                        `).join('');
                    } else {
                        pkgListHtml = '<span style="color:var(--text-muted); font-size:12px;">No packages required.</span>';
                    }

                    // Render wheels list
                    let wheelsHtml = '';
                    if (pack.wheels && pack.wheels.length > 0) {
                        wheelsHtml = pack.wheels.map(whl => `
                            <span class="wheel-badge" title="${escapeHtml(whl)}">${escapeHtml(whl)}</span>
                        `).join('');
                    } else {
                        wheelsHtml = '<span style="color:var(--text-muted); font-size:11px;">No offline wheels cached.</span>';
                    }

                    card.innerHTML = `
                        <div class="pack-meta-section">
                            <div class="pack-card-top">
                                <h3><span class="btn-icon">📁</span> ${escapeHtml(pack.name)}</h3>
                                <span class="pack-py-badge">Python ${escapeHtml(pack.required_python)}</span>
                            </div>
                            <p class="pack-card-desc">${escapeHtml(pack.description || 'Custom project environment pack features.')}</p>
                            
                            <div class="pack-actions-bar">
                                <button class="btn btn-success" onclick="installPack('${escapeJs(pack.name)}')">Install Pack</button>
                                <button class="btn btn-secondary" style="border-color:rgba(255,82,82,0.3); color:var(--color-error);" onclick="deletePack('${escapeJs(pack.name)}')">Delete Pack</button>
                            </div>
                        </div>
                        
                        <div class="pack-details-section">
                            <div>
                                <h4 style="font-size:14px; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
                                    <span>Packages & Dependencies</span>
                                    <div style="display: flex; gap: 6px;">
                                        <button class="btn btn-secondary" style="padding: 2px 8px; font-size: 11px; background: rgba(52, 152, 219, 0.15); color: #3498db; border-color: rgba(52, 152, 219, 0.3);" onclick="downloadAllWheels('${escapeJs(pack.name)}')">↓ Cache Wheels</button>
                                        <button class="btn btn-secondary" style="padding: 2px 8px; font-size: 11px;" onclick="openAddPackageModal('${escapeJs(pack.name)}')">+ Add Package</button>
                                    </div>
                                </h4>
                                <div class="pkg-list-container">
                                    ${pkgListHtml}
                                </div>
                            </div>
                            
                            <div>
                                <h4 style="font-size:14px; margin-bottom:8px;">Offline Wheel Cache (.whl)</h4>
                                <div class="wheels-list-container">
                                    ${wheelsHtml}
                                </div>
                            </div>
                        </div>
                    `;
                    feed.appendChild(card);
                });
            } catch (err) {
                log(`Failed to load project packs: ${err.message}`, 'error');
            }
        }

        async function installPack(name) {
            log(`Initializing Project Pack installation: ${name}...`, 'warning');
            try {
                const res = await fetch('/api/packs/install', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name })
                });
                const result = await res.json();
                
                log(`Spawned package installation for '${name}': ${result.message}`, 'info');
                pollPackInstallLogs(name);
            } catch (err) {
                log(`Failed to install pack '${name}': ${err.message}`, 'error');
            }
        }

        async function pollPackInstallLogs(name) {
            log(`Installing virtual environment dependencies for pack: ${name}...`, 'info');
        }

        async function deletePack(name) {
            if (!confirm(`Are you absolutely sure you want to delete the project pack '${name}'? This will delete all its metadata, requirements, and offline wheel cache.`)) return;
            log(`Deleting project pack: ${name}...`, 'warning');
            try {
                const res = await fetch('/api/packs/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name })
                });
                const result = await res.json();
                if (result.success) {
                    log(`Deleted project pack '${name}' successfully.`, 'success');
                    loadPacks();
                } else {
                    log(`Failed to delete project pack: ${result.error}`, 'error');
                }
            } catch (err) {
                log(`Failed to delete pack: ${err.message}`, 'error');
            }
        }

        async function downloadAllWheels(name) {
            log(`Requesting offline wheel caching for all requirements in pack '${name}'...`, 'warning');
            try {
                const res = await fetch('/api/packs/wheels/download_all', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name })
                });
                const result = await res.json();
                log(result.message, 'success');
                setTimeout(loadPacks, 3000);
            } catch (err) {
                log(`Failed to cache wheels: ${err.message}`, 'error');
            }
        }

        async function openAddPackageModal(packName) {
            const pkgName = prompt(`Enter package name to add to pack '${packName}' (will automatically download offline wheel cache):`);
            if (!pkgName || !pkgName.trim()) return;
            await addPackageToPack(packName, pkgName.trim());
        }

        async function addPackageToPack(pack, package) {
            log(`Adding package '${package}' to pack '${pack}' and downloading offline wheels...`, 'warning');
            try {
                const res = await fetch('/api/packs/packages/add', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ pack, package })
                });
                const result = await res.json();
                if (result.success) {
                    log(`Successfully added package '${package}' and updated wheels.`, 'success');
                    loadPacks();
                } else {
                    log(`Failed to add package: ${result.error}`, 'error');
                }
            } catch (err) {
                log(`Failed to add package: ${err.message}`, 'error');
            }
        }

        async function removePackageFromPack(pack, package) {
            if (!confirm(`Are you sure you want to remove package '${package}' from pack '${pack}'? This will also purge its offline wheel files.`)) return;
            log(`Removing package '${package}' from pack '${pack}'...`, 'warning');
            try {
                const res = await fetch('/api/packs/packages/remove', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ pack, package })
                });
                const result = await res.json();
                if (result.success) {
                    log(`Successfully removed package '${package}' and purged offline wheels.`, 'success');
                    loadPacks();
                } else {
                    log(`Failed to remove package: ${result.error}`, 'error');
                }
            } catch (err) {
                log(`Failed to remove package: ${err.message}`, 'error');
            }
        }

        function openCreatePackModal() {
            document.getElementById('create-pack-modal').classList.add('active');
        }

        function closeCreatePackModal() {
            document.getElementById('create-pack-modal').classList.remove('active');
            document.getElementById('new-pack-name').value = '';
            document.getElementById('new-pack-py').value = '3.11';
            document.getElementById('new-pack-desc').value = '';
        }

        async function submitNewPack() {
            const name = document.getElementById('new-pack-name').value.trim();
            const required_python = document.getElementById('new-pack-py').value.trim();
            const description = document.getElementById('new-pack-desc').value.trim();

            if (!name) {
                alert("Please enter a pack folder name.");
                return;
            }

            log(`Creating custom project pack '${name}'...`, 'warning');
            try {
                const res = await fetch('/api/packs/create', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, required_python, description })
                });
                const result = await res.json();
                if (result.success) {
                    log(`Created project pack '${name}' successfully.`, 'success');
                    closeCreatePackModal();
                    loadPacks();
                } else {
                    log(`Failed to create pack: ${result.error}`, 'error');
                }
            } catch (err) {
                log(`Failed to create pack: ${err.message}`, 'error');
            }
        }

        // Modal triggers
        function openAddMemoryModal() {
            document.getElementById('add-memory-modal').classList.add('active');
        }

        function closeAddMemoryModal() {
            document.getElementById('add-memory-modal').classList.remove('active');
            document.getElementById('mem-key').value = '';
            document.getElementById('mem-val').value = '';
            document.getElementById('mem-tags').value = '';
        }

        async function submitNewMemory() {
            const key = document.getElementById('mem-key').value.trim();
            const value = document.getElementById('mem-val').value.trim();
            const tagsInput = document.getElementById('mem-tags').value.trim();

            if (!key || !value) {
                alert("Please fill in key and value fields!");
                return;
            }

            const tags = tagsInput ? tagsInput.split(',').map(t => t.trim()) : [];
            log(`Saving memory context for '${key}'...`, 'info');

            try {
                const res = await fetch('/api/memory/remember', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key, value, tags })
                });
                const result = await res.json();
                
                if (result.success) {
                    log(`Stored memory record: '${key}' successfully.`, 'success');
                    closeAddMemoryModal();
                    loadMemories();
                } else {
                    log(`Failed to store memory: ${result.error}`, 'error');
                }
            } catch (err) {
                log(`Failed to remember key: ${err.message}`, 'error');
            }
        }

        // Subagent Orchestration JS logic
        function onPresetCmdChange() {
            const select = document.getElementById('subagent-preset-cmd');
            const customInput = document.getElementById('subagent-custom-cmd');
            if (select.value === 'custom') {
                customInput.style.display = 'block';
            } else {
                customInput.style.display = 'none';
            }
        }

        async function spawnSubagent() {
            const select = document.getElementById('subagent-preset-cmd');
            let command = select.value;
            if (command === 'custom') {
                command = document.getElementById('subagent-custom-cmd').value.trim();
            } else if (command === '') {
                alert("Please select a task to spawn!");
                return;
            }

            log(`Spawning subagent: "${command}"...`, 'info');
            try {
                const res = await fetch('/api/subagents/spawn', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ command })
                });
                const result = await res.json();
                if (result.id) {
                    log(`Subagent spawned successfully with ID: ${result.id}`, 'success');
                    updateSubagentsList();
                } else {
                    log(`Failed to spawn subagent: ${result.error}`, 'error');
                }
            } catch (err) {
                log(`Failed to spawn subagent: ${err.message}`, 'error');
            }
        }

        async function killSubagent(id) {
            log(`Terminating subagent process: ${id}...`, 'warning');
            try {
                const res = await fetch('/api/subagents/kill', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id })
                });
                const result = await res.json();
                if (result.success) {
                    log(`Subagent ${id} terminated.`, 'success');
                    updateSubagentsList();
                } else {
                    log(`Failed to terminate subagent: ${result.error}`, 'error');
                }
            } catch (err) {
                log(`Failed to terminate subagent: ${err.message}`, 'error');
            }
        }

        let subagentLogsCache = {}; // id -> string length

        async function updateSubagentsList() {
            try {
                // Also update watcher badge
                const statusRes = await fetch('/api/status');
                const statusData = await statusRes.json();
                if (statusData.watcher_status) {
                    const badge = document.getElementById('watcher-badge');
                    badge.textContent = `Watcher: ${statusData.watcher_status}`;
                    if (statusData.watcher_status.includes('Reindexing')) {
                        badge.style.background = 'rgba(255, 215, 0, 0.1)';
                        badge.style.color = 'var(--color-warning)';
                    } else {
                        badge.style.background = 'rgba(0, 229, 255, 0.1)';
                        badge.style.color = 'var(--color-primary)';
                    }
                }

                const res = await fetch('/api/subagents/list');
                const subagents = await res.json();
                const feed = document.getElementById('subagents-feed');

                if (subagents.length === 0) {
                    feed.innerHTML = '<div class="empty-state">No background subagent processes launched yet.</div>';
                    return;
                }

                // Render each subagent card
                let html = '';
                subagents.forEach(agent => {
                    const statusClass = agent.status.toLowerCase();
                    const isRunning = agent.status === 'Running';
                    const termId = `term-${agent.id}`;
                    
                    html += `
                        <div class="subagent-item-card">
                            <div class="subagent-item-header">
                                <div class="subagent-item-meta">
                                    <span class="subagent-cmd-text">${escapeHtml(agent.command)}</span>
                                    <span class="subagent-badge ${statusClass}">${agent.status}</span>
                                    <span style="font-size:11px; color:var(--text-muted)">ID: ${agent.id} | Started: ${new Date(agent.started).toLocaleTimeString()}</span>
                                </div>
                                <div>
                                    ${isRunning ? `<button class="btn btn-error btn-icon" onclick="killSubagent('${agent.id}')">✕ Terminate</button>` : ''}
                                </div>
                            </div>
                            <div class="subagent-terminal" id="${termId}">${escapeHtml(agent.logs)}</div>
                        </div>
                    `;
                });

                feed.innerHTML = html;

                // Adjust terminal scrolling if new logs appended
                subagents.forEach(agent => {
                    const termEl = document.getElementById(`term-${agent.id}`);
                    if (termEl) {
                        const cachedLen = subagentLogsCache[agent.id] || 0;
                        if (agent.logs.length > cachedLen) {
                            termEl.scrollTop = termEl.scrollHeight;
                            subagentLogsCache[agent.id] = agent.logs.length;
                        }
                    }
                });
            } catch (err) {
                console.error("Error updating subagents:", err);
            }
        }

        // Utilities
        function escapeHtml(str) {
            if (!str) return '';
            return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }

        function escapeJs(str) {
            if (!str) return '';
            return str.replace(/'/g, "\\'");
        }

        // Reload Preemptive Status
        async function reloadPreemptiveStatus() {
            try {
                const res = await fetch('/api/preemptive/status');
                if (!res.ok) return;
                const data = await res.json();
                
                const badge = document.getElementById('daemon-badge');
                if (badge) badge.textContent = `Daemon: ${data.status || 'Active'}`;
                
                const lastCheckedEl = document.getElementById('daemon-last-checked');
                if (lastCheckedEl) lastCheckedEl.textContent = data.last_checked || '--';
                
                const syntaxErrors = data.syntax_errors || [];
                const testResults = data.test_results || {};
                const rippleWarnings = data.ripple_warnings || [];
                
                const syntaxVal = document.getElementById('health-stat-syntax');
                if (syntaxVal) {
                    syntaxVal.textContent = syntaxErrors.length;
                    syntaxVal.style.color = syntaxErrors.length > 0 ? 'var(--color-error)' : 'var(--color-success)';
                }
                
                const passedVal = document.getElementById('health-stat-passed');
                if (passedVal) passedVal.textContent = testResults.passed || 0;
                
                const failedVal = document.getElementById('health-stat-failed');
                if (failedVal) {
                    failedVal.textContent = testResults.failed || 0;
                    failedVal.style.color = (testResults.failed || 0) > 0 ? 'var(--color-error)' : 'var(--color-success)';
                }
                
                const testStatusEl = document.getElementById('daemon-test-status');
                if (testStatusEl) {
                    if ((testResults.failed || 0) > 0) {
                        testStatusEl.textContent = 'Unhealthy (Suite Failures)';
                        testStatusEl.style.color = 'var(--color-error)';
                    } else {
                        testStatusEl.textContent = testResults.status || 'Healthy';
                        testStatusEl.style.color = 'var(--color-success)';
                    }
                }
                
                const errContainer = document.getElementById('health-errors-container');
                if (errContainer) {
                    if (syntaxErrors.length > 0) {
                        errContainer.style.display = 'flex';
                        errContainer.innerHTML = '<h4 style="margin-top:10px;">Syntax Error Warnings:</h4>' + syntaxErrors.map(err => `
                            <div class="health-error-item">
                                <div class="health-error-title">${err.file} (Line ${err.line})</div>
                                <div style="color:var(--text-bright); font-family:var(--font-mono); margin-bottom:4px;">${err.error}</div>
                                <div style="color:var(--text-muted); font-size:11px; background:rgba(0,0,0,0.2); padding:4px; border-radius:4px;">${err.text}</div>
                            </div>
                        `).join('');
                    } else {
                        errContainer.style.display = 'none';
                    }
                }
                
                const warnContainer = document.getElementById('health-warnings-container');
                if (warnContainer) {
                    if (rippleWarnings.length > 0) {
                        warnContainer.style.display = 'flex';
                        warnContainer.innerHTML = '<h4 style="margin-top:10px;">Downstream Ripple Warnings:</h4>' + rippleWarnings.map(warn => `
                            <div class="health-warning-item">
                                <div class="health-warning-title">Modifying ${warn.modified_file} affects ${warn.impacted_count} files</div>
                                <div style="color:var(--text-muted); font-size:11px; margin-top:4px;">
                                    Impacted files: ${warn.impacted_files.map(f => `<code style="color:var(--color-primary); font-family:var(--font-mono);">${f}</code>`).join(', ')}
                                </div>
                            </div>
                        `).join('');
                    } else {
                        warnContainer.style.display = 'none';
                    }
                }
            } catch (e) {
                console.error("Failed to load preemptive status:", e);
            }
        }

        // Reload Codebase Dependency Graph
        async function reloadDependencyGraph() {
            const container = document.getElementById('graph-feed-container');
            if (!container) return;
            container.innerHTML = '<div class="empty-state">Loading codebase dependency graph...</div>';
            try {
                const res = await fetch('/api/preemptive/graph');
                if (!res.ok) throw new Error("API failure");
                const data = await res.json();
                
                const files = data.files || {};
                const fileKeys = Object.keys(files);
                
                if (fileKeys.length === 0) {
                    container.innerHTML = '<div class="empty-state">No source files indexed yet. Re-index codebase first.</div>';
                    return;
                }
                
                let html = '<div style="display:flex; flex-direction:column; gap:8px;">';
                for (const key of fileKeys) {
                    const meta = files[key];
                    const classes = meta.classes || [];
                    const functions = meta.functions || [];
                    const imports = meta.imports || [];
                    const language = meta.language || 'unknown';
                    
                    const depList = data.dependencies[key] || [];
                    const node_id = key.replace(/[^a-zA-Z0-9]/g, '_');
                    
                    html += `
                        <div style="background:rgba(255,255,255,0.01); border:1px solid rgba(255,255,255,0.02); border-radius:8px; padding:10px;">
                            <div class="graph-file-item" onclick="toggleGraphNode('${key}')">
                                <span class="graph-badge-lang ${language}">${language}</span>
                                <span style="font-weight:600; color:var(--text-bright);">${key.split('/').pop()}</span>
                                <span style="font-size:11px; color:var(--text-muted);">${key}</span>
                            </div>
                            <div id="graph-node-details-${node_id}" class="graph-tree-node" style="display:none;">
                                ${classes.length > 0 ? `
                                    <div style="margin-bottom:6px;">
                                        <strong style="font-size:12px; color:var(--color-primary);">Classes:</strong>
                                        <div style="margin-left:12px; font-size:12px; font-family:var(--font-mono); color:#e1e1e1;">
                                            ${classes.map(c => {
                                                const parent = data.inheritance[c];
                                                return `class ${c}${parent ? ` extends <span style="color:var(--color-warning);">${parent}</span>` : ''}`;
                                            }).join('<br>')}
                                        </div>
                                    </div>
                                ` : ''}
                                ${functions.length > 0 ? `
                                    <div style="margin-bottom:6px;">
                                        <strong style="font-size:12px; color:var(--color-primary);">Functions:</strong>
                                        <div style="margin-left:12px; font-size:12px; font-family:var(--font-mono); color:#d1d1d1;">
                                            ${functions.map(f => `def ${f}()`).join(', ')}
                                        </div>
                                    </div>
                                ` : ''}
                                ${depList.length > 0 ? `
                                    <div>
                                        <strong style="font-size:12px; color:var(--color-warning);">Imports:</strong>
                                        <div style="margin-left:12px; font-size:11px; font-family:var(--font-mono); color:var(--text-muted);">
                                            ${depList.map(dep => `import "${dep.split('/').pop()}"`).join(', ')}
                                        </div>
                                    </div>
                                ` : ''}
                            </div>
                        </div>
                    `;
                }
                html += '</div>';
                container.innerHTML = html;
            } catch (e) {
                container.innerHTML = `<div class="empty-state" style="color:var(--color-error)">Failed to load graph: ${e.message}</div>`;
            }
        }
        
        function toggleGraphNode(key) {
            const node_id = key.replace(/[^a-zA-Z0-9]/g, '_');
            const element = document.getElementById(`graph-node-details-${node_id}`);
            if (element) {
                element.style.display = element.style.display === 'none' ? 'block' : 'none';
            }
        }

        // Reload Audit Ledger
        async function reloadAuditLedger() {
            const container = document.getElementById('ledger-feed-container');
            if (!container) return;
            container.innerHTML = '<div class="empty-state">Loading recorded actions...</div>';
            try {
                const res = await fetch('/api/activity/list');
                if (!res.ok) throw new Error("API failure");
                const data = await res.json();
                
                if (data.length === 0) {
                    container.innerHTML = '<div class="empty-state">No agent actions recorded yet.</div>';
                    return;
                }
                
                container.innerHTML = data.map(act => {
                    const statusClass = (act.result_status === 'success' || act.result_status === 'Success') ? 'success' : 'failed';
                    return `
                        <div class="ledger-item">
                            <div class="ledger-meta">
                                <span>${act.timestamp}</span>
                                <span class="ledger-badge ${statusClass}">${act.result_status}</span>
                            </div>
                            <div class="ledger-tool">${act.tool_name}</div>
                            <div class="ledger-summary">${act.summary}</div>
                            ${act.arguments ? `<div class="ledger-args">Arguments: ${act.arguments}</div>` : ''}
                        </div>
                    `;
                }).join('');
            } catch (e) {
                container.innerHTML = `<div class="empty-state" style="color:var(--color-error)">Failed to load ledger: ${e.message}</div>`;
            }
        }

        // Init loads
        window.addEventListener('DOMContentLoaded', () => {
            runDiagnostics();
            loadMemories();
            loadPacks();
            updateSubagentsList();
            setInterval(updateSubagentsList, 1500);
            
            // Initial load of new panels
            reloadPreemptiveStatus();
            reloadDependencyGraph();
            reloadAuditLedger();
            
            // Setup periodic refresh
            setInterval(reloadPreemptiveStatus, 4000);
            setInterval(reloadAuditLedger, 5000);
        });
    </script>
</body>
</html>
"""


class BackgroundTaskTracker:
    """Track progress of a long running background indexing task."""
    status = "Idle"
    logs = []
    _lock = threading.Lock()

    @classmethod
    def set_status(cls, new_status: str):
        with cls._lock:
            cls.status = new_status

    @classmethod
    def get_status(cls) -> str:
        with cls._lock:
            return cls.status

    @classmethod
    def add_log(cls, msg: str):
        with cls._lock:
            cls.logs.append(msg)

    @classmethod
    def get_logs(cls) -> list:
        with cls._lock:
            current = list(cls.logs)
            cls.logs.clear()
            return current


class SubagentTask:
    def __init__(self, command: str, root_dir: Path):
        self.id = "agent_" + str(uuid.uuid4())[:8]
        self.command = command
        self.root_dir = root_dir
        self.status = "Running"
        self.started = datetime.utcnow().isoformat() + 'Z'
        self.ended = None
        self.logs = ""
        self.process = None
        self._lock = threading.Lock()

    def start(self):
        def run_proc():
            try:
                env = os.environ.copy()
                import shlex
                cmd_args = shlex.split(self.command, posix=(os.name != 'nt'))
                self.process = subprocess.Popen(
                    cmd_args,
                    shell=False,
                    cwd=str(self.root_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=env
                )
                
                for line in iter(self.process.stdout.readline, ''):
                    with self._lock:
                        self.logs += line
                
                self.process.wait()
                with self._lock:
                    if self.status == "Running":
                        if self.process.returncode == 0:
                            self.status = "Completed"
                        else:
                            self.status = "Failed"
            except Exception as e:
                with self._lock:
                    self.logs += f"\n[ORCHESTRATOR ERROR] Failed to run command: {e}\n"
                    self.status = "Failed"
            finally:
                with self._lock:
                    self.ended = datetime.utcnow().isoformat() + 'Z'

        threading.Thread(target=run_proc, daemon=True).start()

    def kill(self):
        with self._lock:
            if self.status == "Running" and self.process:
                try:
                    self.process.terminate()
                except Exception:
                    pass
                self.status = "Killed"
                self.logs += "\n[ORCHESTRATOR] Process terminated by user request.\n"
                self.ended = datetime.utcnow().isoformat() + 'Z'

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "command": self.command,
                "status": self.status,
                "started": self.started,
                "ended": self.ended,
                "logs": self.logs
            }


class SubagentOrchestrator:
    tasks: Dict[str, SubagentTask] = {}
    _lock = threading.Lock()

    @classmethod
    def spawn(cls, command: str, root_dir: Path) -> str:
        task = SubagentTask(command, root_dir)
        with cls._lock:
            cls.tasks[task.id] = task
        task.start()
        return task.id

    @classmethod
    def kill(cls, task_id: str) -> bool:
        with cls._lock:
            task = cls.tasks.get(task_id)
        if task:
            task.kill()
            return True
        return False

    @classmethod
    def list_all(cls) -> list:
        with cls._lock:
            return [t.to_dict() for t in cls.tasks.values()]


class IdleWatcherThread:
    """Lightweight background thread to perform idle-time file reindexing."""
    last_request_time = time.time()
    watcher_status = "Active (Idle)"
    _lock = threading.Lock()
    file_hashes: Dict[str, str] = {}
    
    @classmethod
    def update_request_time(cls):
        with cls._lock:
            cls.last_request_time = time.time()

    @classmethod
    def get_watcher_status(cls) -> str:
        with cls._lock:
            return cls.watcher_status

    @classmethod
    def set_watcher_status(cls, status: str):
        with cls._lock:
            cls.watcher_status = status

    @classmethod
    def get_file_hash(cls, path: Path) -> str:
        try:
            with open(path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception:
            return ""

    @classmethod
    def start(cls, root: Path):
        def loop():
            from .utils import find_python_files
            from .vector_store import VectorStore

            try:
                for path in find_python_files(root):
                    cls.file_hashes[str(path)] = cls.get_file_hash(path)
            except Exception:
                pass

            while True:
                time.sleep(2.0)
                
                if BackgroundTaskTracker.get_status() == "Running":
                    continue

                with cls._lock:
                    is_idle = (time.time() - cls.last_request_time) > 5.0

                if is_idle:
                    changed_files = []
                    try:
                        current_files = list(find_python_files(root))
                        for path in current_files:
                            path_str = str(path)
                            h = cls.get_file_hash(path)
                            if cls.file_hashes.get(path_str) != h:
                                cls.file_hashes[path_str] = h
                                changed_files.append(path)
                    except Exception:
                        pass

                    if changed_files:
                        cls.set_watcher_status("Reindexing...")
                        try:
                            store = VectorStore()
                            store.index_codebase(root, changed_files=changed_files)
                        except Exception:
                            pass
                        cls.set_watcher_status("Active (Idle)")

        threading.Thread(target=loop, daemon=True).start()


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Multi-threaded socket HTTP Server."""
    daemon_threads = True


class DashboardHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    """Router for all GUI HTTP REST APIs and SPA asset streaming."""

    def log_message(self, format, *args):
        # Silence default terminal logs of HTTP requests
        pass

    def send_json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def do_GET(self):
        IdleWatcherThread.update_request_time()
        url = urllib.parse.urlparse(self.path)
        path = url.path

        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode('utf-8'))
            return

        elif path == "/favicon.ico":
            self.send_response(200)
            self.send_header("Content-Type", "image/x-icon")
            self.end_headers()
            self.wfile.write(b"")
            return

        elif path == "/api/status":
            root = find_project_root() or Path.cwd()
            self.send_json({
                "root": str(root),
                "platform": sys.platform,
                "python_version": sys.version.split()[0],
                "watcher_status": IdleWatcherThread.get_watcher_status()
            })
            return

        elif path == "/api/subagents/list":
            self.send_json(SubagentOrchestrator.list_all())
            return

        elif path == "/api/doctor":
            root = find_project_root() or Path.cwd()
            # Run doctor --json checks
            doctor = Doctor(root)
            results = doctor.run_all()
            health_score = 100
            errors = sum(1 for r in results if r['status'] == 'error')
            warns = sum(1 for r in results if r['status'] == 'warn')
            health_score = max(0, 100 - (errors * 25) - (warns * 10))
            
            self.send_json({
                "health_score": health_score,
                "root": str(root),
                "diagnostics": results,
                "issues": [{"type": i[0], "description": i[1]} for i in doctor.issues]
            })
            return

        elif path == "/api/index/status":
            self.send_json({
                "status": BackgroundTaskTracker.get_status(),
                "logs": BackgroundTaskTracker.get_logs()
            })
            return

        elif path == "/api/memory/list":
            try:
                store = MemoryStore()
                memories_list = []
                for key, mem in store.memories.items():
                    memories_list.append({
                        "key": mem.key,
                        "value": mem.value,
                        "tags": mem.tags,
                        "created": mem.created,
                        "updated": mem.updated
                    })
                self.send_json(memories_list)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        elif path == "/api/packs/list":
            root = find_project_root() or Path.cwd()
            packs_dir = root / 'project_packs'
            packs = []
            if packs_dir.exists():
                for item in packs_dir.iterdir():
                    if item.is_dir() and not item.name.startswith('.'):
                        pack_info = {
                            "name": item.name,
                            "required_python": "3.11",
                            "description": "",
                            "requirements": [],
                            "wheels": []
                        }
                        # Read pack.json
                        pack_json = item / "pack.json"
                        if pack_json.exists():
                            try:
                                with open(pack_json, "r") as f:
                                    meta = json.load(f)
                                    pack_info["required_python"] = meta.get("required_python", "3.11")
                                    pack_info["description"] = meta.get("description", "")
                            except Exception:
                                pass
                        
                        # Read requirements.txt
                        req_file = item / "requirements.txt"
                        if req_file.exists():
                            try:
                                with open(req_file, "r") as f:
                                    pack_info["requirements"] = [
                                        line.strip() for line in f.readlines()
                                        if line.strip() and not line.strip().startswith('#')
                                    ]
                            except Exception:
                                pass
                                
                        # List wheels
                        wheels_dir = item / "wheels"
                        if wheels_dir.exists():
                            try:
                                pack_info["wheels"] = [
                                    w.name for w in wheels_dir.glob("*.whl")
                                ]
                            except Exception:
                                pass
                        
                        # Get package caching status
                        try:
                            from .pack_manager import get_pack_package_status
                            pack_info["requirements_status"] = get_pack_package_status(item.name)
                        except Exception:
                            pack_info["requirements_status"] = []
                        
                        packs.append(pack_info)
            self.send_json(packs)
            return

        elif path == "/api/preemptive/status":
            try:
                from .preemptive_daemon import PreemptiveDaemon
                health = PreemptiveDaemon.get_health()
                self.send_json(health)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        elif path == "/api/preemptive/graph":
            try:
                from .dependency_graph import MacroCodebaseGraph
                graph = MacroCodebaseGraph()
                if not graph.load():
                    graph.build()
                
                self.send_json({
                    "files": graph.files,
                    "dependencies": graph.dependencies,
                    "dependents": {k: list(v) for k, v in graph.dependents.items()},
                    "inheritance": graph.inheritance
                })
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        elif path == "/api/activity/list":
            try:
                from .memory import get_store
                store = get_store()
                cursor = store.conn.cursor()
                cursor.execute("SELECT id, timestamp, tool_name, arguments, result_status, summary FROM activity_ledger ORDER BY timestamp DESC LIMIT 50")
                activities = []
                for row in cursor.fetchall():
                    activities.append({
                        "id": row[0],
                        "timestamp": row[1],
                        "tool_name": row[2],
                        "arguments": row[3],
                        "result_status": row[4],
                        "summary": row[5]
                    })
                self.send_json(activities)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        IdleWatcherThread.update_request_time()
        url = urllib.parse.urlparse(self.path)
        path = url.path

        # Parse request body size
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length) if content_length > 0 else b""
        
        body = {}
        if post_data:
            try:
                body = json.loads(post_data.decode('utf-8'))
            except Exception:
                pass

        if path == "/api/doctor/fix":
            root = find_project_root() or Path.cwd()
            doctor = Doctor(root)
            success = doctor.repair()
            self.send_json({
                "success": success,
                "fixes": doctor.fixes_applied,
                "error": "Manual intervention required for remaining issues" if not success else ""
            })
            return

        elif path == "/api/subagents/spawn":
            command = body.get('command')
            if not command:
                self.send_json({"error": "Missing command"}, 400)
                return
            root = find_project_root() or Path.cwd()
            task_id = SubagentOrchestrator.spawn(command, root)
            self.send_json({"id": task_id, "status": "Running"})
            return

        elif path == "/api/subagents/kill":
            task_id = body.get('id')
            if not task_id:
                self.send_json({"error": "Missing subagent ID"}, 400)
                return
            success = SubagentOrchestrator.kill(task_id)
            self.send_json({"success": success})
            return

        elif path == "/api/index/all":
            # Spawn indexing in separate thread
            full = body.get('full', False)
            root = find_project_root() or Path.cwd()
            
            if BackgroundTaskTracker.get_status() == "Running":
                self.send_json({"error": "Indexing is already running"}, 400)
                return

            def background_indexing():
                BackgroundTaskTracker.set_status("Running")
                BackgroundTaskTracker.add_log(f"[INFO] Initializing indexing. Mode: {'Full' if full else 'Incremental'}")
                try:
                    from .index_all import run_all_indexes
                    # Custom output redirector to hook Console logs
                    orig_ok = Console.ok
                    orig_info = Console.info
                    orig_warn = Console.warn
                    orig_fail = Console.fail

                    Console.ok = lambda msg: (orig_ok(msg), BackgroundTaskTracker.add_log(f"[OK] {msg}"))
                    Console.info = lambda msg: (orig_info(msg), BackgroundTaskTracker.add_log(f"[INFO] {msg}"))
                    Console.warn = lambda msg: (orig_warn(msg), BackgroundTaskTracker.add_log(f"[WARNING] {msg}"))
                    Console.fail = lambda msg: (orig_fail(msg), BackgroundTaskTracker.add_log(f"[FAIL] {msg}"))

                    run_all_indexes(root, verbose=True, force_full=full)

                    # Restore
                    Console.ok = orig_ok
                    Console.info = orig_info
                    Console.warn = orig_warn
                    Console.fail = orig_fail

                    BackgroundTaskTracker.set_status("Complete")
                except Exception as e:
                    BackgroundTaskTracker.add_log(f"[FAIL] Error building index: {str(e)}")
                    BackgroundTaskTracker.set_status("Failed")

            threading.Thread(target=background_indexing, daemon=True).start()
            self.send_json({"message": "Codebase indexing has been scheduled."})
            return

        elif path == "/api/memory/remember":
            key = body.get('key')
            val = body.get('value')
            tags = body.get('tags', [])

            if not key or not val:
                self.send_json({"error": "Missing key or value"}, 400)
                return

            try:
                store = MemoryStore()
                # Create/update memory
                now = datetime.utcnow().isoformat() + 'Z'
                if key in store.memories:
                    mem = store.memories[key]
                    mem.value = val
                    mem.tags = list(set(mem.tags + tags))
                    mem.updated = now
                else:
                    mem = Memory(key=key, value=val, tags=tags, created=now, updated=now)
                    store.memories[key] = mem

                store.save()
                self.send_json({"success": True})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        elif path == "/api/memory/forget":
            key = body.get('key')
            if not key:
                self.send_json({"error": "Missing key"}, 400)
                return

            try:
                store = MemoryStore()
                if key in store.memories:
                    del store.memories[key]
                    store.save()
                    self.send_json({"success": True})
                else:
                    self.send_json({"error": "Memory key not found"}, 404)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        elif path == "/api/packs/install":
            name = body.get('name')
            if not name:
                self.send_json({"error": "Missing pack name"}, 400)
                return

            root = find_project_root() or Path.cwd()
            
            def background_install():
                mcp_script = root / 'mcp-agentic-rules' / 'mcp.py'
                subprocess.run([sys.executable, str(mcp_script), 'pack', 'install', name], cwd=root)

            threading.Thread(target=background_install, daemon=True).start()
            self.send_json({"message": f"Installation scheduled for project pack '{name}'."})
            return

        elif path == "/api/packs/create":
            name = body.get('name')
            py_ver = body.get('required_python', '3.11')
            desc = body.get('description', '')
            if not name:
                self.send_json({"error": "Missing pack name"}, 400)
                return
            from .pack_manager import create_pack
            success = create_pack(name, py_ver, desc)
            self.send_json({"success": success})
            return

        elif path == "/api/packs/delete":
            name = body.get('name')
            if not name:
                self.send_json({"error": "Missing pack name"}, 400)
                return
            from .pack_manager import delete_pack
            success = delete_pack(name)
            self.send_json({"success": success})
            return

        elif path == "/api/packs/packages/add":
            pack = body.get('pack')
            package = body.get('package')
            if not pack or not package:
                self.send_json({"error": "Missing pack name or package name"}, 400)
                return
            from .pack_manager import add_package_to_pack
            success = add_package_to_pack(pack, package)
            self.send_json({"success": success})
            return

        elif path == "/api/packs/packages/remove":
            pack = body.get('pack')
            package = body.get('package')
            if not pack or not package:
                self.send_json({"error": "Missing pack name or package name"}, 400)
                return
            from .pack_manager import remove_package_from_pack
            success = remove_package_from_pack(pack, package)
            self.send_json({"success": success})
            return

        elif path == "/api/packs/wheels/download_all":
            name = body.get('name')
            if not name:
                self.send_json({"error": "Missing pack name"}, 400)
                return
            
            def background_download():
                from .pack_manager import download_pack_wheels
                download_pack_wheels(name)
                
            threading.Thread(target=background_download, daemon=True).start()
            self.send_json({"message": f"Started background offline wheels download for '{name}'."})
            return

        self.send_response(404)
        self.end_headers()


def get_free_port(start_port: int = 8550) -> int:
    """Find a free TCP port to bind the server to."""
    port = start_port
    while port < start_port + 100:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return port
        except OSError:
            port += 1
    return start_port


def main():
    """CLI launcher for local dashboard."""
    # Parse port if provided
    port = 8550
    if '--port' in sys.argv:
        try:
            idx = sys.argv.index('--port')
            port = int(sys.argv[idx + 1])
        except Exception:
            pass

    port = get_free_port(port)
    url = f"http://127.0.0.1:{port}/"

    Console.header("MCP Global Local Dashboard Server")
    Console.info(f"Binding HTTP web server to port {port}...")
    Console.info(f"URL endpoint: {url}")

    # Launch server
    server_address = ('127.0.0.1', port)
    
    try:
        httpd = ThreadingHTTPServer(server_address, DashboardHTTPRequestHandler)
        # Start the idle watcher thread
        root = find_project_root() or Path.cwd()
        IdleWatcherThread.start(root)
        
        # Start the Preemptive Automation Daemon
        try:
            from .preemptive_daemon import PreemptiveDaemon
            PreemptiveDaemon.start(root)
            Console.info("Preemptive Background Automation Daemon spawned successfully.")
        except Exception as e:
            Console.warn(f"Failed to start Preemptive Automation Daemon: {e}")
    except Exception as e:
        Console.fail(f"Could not start HTTP server on port {port}: {e}")
        return 1

    # Automatically launch browser in separate thread so it doesn't block server startup
    def launch_browser():
        time.sleep(1.0)
        Console.info("Launching default system web browser...")
        webbrowser.open(url)

    threading.Thread(target=launch_browser, daemon=True).start()

    Console.ok("Control Center server is online! Press Ctrl+C to stop.")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("")
        Console.info("Stopping HTTP local dashboard server...")
        try:
            from .preemptive_daemon import PreemptiveDaemon
            PreemptiveDaemon.stop()
            Console.info("Preemptive Background Automation Daemon stopped successfully.")
        except Exception:
            pass
        httpd.server_close()
        Console.ok("Server stopped successfully.")
        return 0
    except Exception as e:
        Console.fail(f"Server error: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
