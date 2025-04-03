#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import shutil
import subprocess
import re
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QListWidget, QPushButton, QMessageBox, 
                            QLabel, QSplitter, QFileDialog, QLineEdit, 
                            QListWidgetItem, QFrame, QTextEdit, QDialog)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QColor, QTextCharFormat, QFont, QSyntaxHighlighter

class WorkingDirectoryHighlighter(QSyntaxHighlighter):
    def __init__(self, document=None):
        super().__init__(document)
        
        # 创建格式
        self.working_dir_format = QTextCharFormat()
        self.working_dir_format.setBackground(QColor(255, 255, 0, 100))  # 淡黄色背景
        self.working_dir_format.setForeground(QColor(0, 0, 0))  # 黑色前景
        self.working_dir_format.setFontWeight(QFont.Bold)
        
        # 需要高亮的应用路径模式
        self.path_patterns = [
            r'/Applications/',
            r'/Application Support/',
            r'/Library/'
        ]
        
        # 用于跟踪上下文的变量
        self.found_working_dir_key = False
    
    def highlightBlock(self, text):
        # 高亮包含特定路径的任何行
        for pattern in self.path_patterns:
            if pattern in text:
                # 高亮整行
                self.setFormat(0, len(text), self.working_dir_format)
                
                # 特别高亮路径部分
                start = text.find(pattern)
                # 如果找到路径，尝试高亮整个引号内的内容或标签内的内容
                if '"' in text[start:]:
                    # 查找路径所在的引号内容
                    quote_start = text.rfind('"', 0, start)
                    quote_end = text.find('"', start)
                    if quote_start != -1 and quote_end != -1:
                        path_length = quote_end - quote_start + 1
                        self.setFormat(quote_start, path_length, self.working_dir_format)
                elif '<string>' in text[:start] and '</string>' in text[start:]:
                    # 查找路径所在的XML标签内容
                    tag_start = text.rfind('<string>', 0, start)
                    tag_end = text.find('</string>', start) + len('</string>')
                    if tag_start != -1 and tag_end != -1:
                        path_length = tag_end - tag_start
                        self.setFormat(tag_start, path_length, self.working_dir_format)
                
                return
                
        # 保留对WorkingDirectory键的跟踪
        if '<key>WorkingDirectory</key>' in text:
            self.found_working_dir_key = True
        elif self.found_working_dir_key and '<string>' in text:
            self.found_working_dir_key = False
        elif '<string>' not in text:
            self.found_working_dir_key = False

class SearchResult:
    def __init__(self, file_name, folder_path, folder_index):
        self.file_name = file_name
        self.folder_path = folder_path
        self.folder_index = folder_index
    
    def __str__(self):
        return f"{self.file_name} ({self.folder_path})"

class FileContentDialog(QDialog):
    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"文件内容: {os.path.basename(file_path)}")
        self.resize(900, 600)
        
        layout = QVBoxLayout(self)
        
        # 文件内容显示区域
        self.content_text = QTextEdit()
        self.content_text.setReadOnly(True)
        layout.addWidget(self.content_text)
        
        # 为文本编辑器添加高亮器
        self.highlighter = WorkingDirectoryHighlighter(self.content_text.document())
        
        # 关闭按钮
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)
        
        # 加载文件内容
        self.load_file_content(file_path)
    
    def load_file_content(self, file_path):
        try:
            # 使用plutil将二进制plist转换为XML格式
            result = subprocess.run(['plutil', '-convert', 'xml1', '-o', '-', file_path], 
                                   capture_output=True, text=True)
            
            if result.returncode == 0:
                content = result.stdout
            else:
                # 如果plutil命令失败，尝试直接读取文件
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            
            self.content_text.setPlainText(content)
            
            # 滚动到WorkingDirectory位置
            self._scroll_to_working_directory()
        except Exception as e:
            self.content_text.setPlainText(f"无法读取文件内容: {str(e)}")
            
    def _scroll_to_working_directory(self):
        """滚动到应用路径位置"""
        document = self.content_text.document()
        cursor = self.content_text.textCursor()
        
        # 从文档开始搜索应用路径
        content = document.toPlainText()
        
        # 查找的路径模式
        path_patterns = ['/Applications/', '/Application Support/']
        
        # 先尝试查找应用路径
        for pattern in path_patterns:
            match_pos = content.find(pattern)
            if match_pos != -1:
                # 找到匹配位置，将光标移动到该位置
                cursor.setPosition(match_pos)
                self.content_text.setTextCursor(cursor)
                
                # 确保找到的位置在视图中间
                self.content_text.ensureCursorVisible()
                return True
        
        # 如果没有找到应用路径，尝试搜索WorkingDirectory
        working_dir_pos = content.find("<key>WorkingDirectory</key>")
        if working_dir_pos != -1:
            cursor.setPosition(working_dir_pos)
            self.content_text.setTextCursor(cursor)
            self.content_text.ensureCursorVisible()
            return True
            
        return False

class LaunchManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("macOS 启动项管理器")
        self.setMinimumSize(1100, 700)
        
        # 默认文件夹列表
        self.folders = [
            os.path.expanduser("~/Library/LaunchAgents"),
            "/System/Library/LaunchAgents",
            "/System/Library/LaunchDaemons",
            "/Library/LaunchAgents",
            "/Library/LaunchDaemons"
        ]
        
        # 存储所有文件的数据结构
        self.all_files = {}  # 格式: {folder_index: {file_name: file_path}}
        
        self.init_ui()
        
    def init_ui(self):
        # 主窗口部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        
        # 顶部搜索区域
        search_layout = QHBoxLayout()
        search_label = QLabel("搜索:")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入关键词搜索所有文件...")
        self.search_button = QPushButton("搜索")
        self.search_button.clicked.connect(self.search_files)
        self.search_input.returnPressed.connect(self.search_files)
        
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_button)
        
        main_layout.addLayout(search_layout)
        
        # 中间搜索结果区域
        search_results_label = QLabel("搜索结果:")
        self.search_results_list = QListWidget()
        self.search_results_list.itemClicked.connect(self.search_result_selected)
        
        main_layout.addWidget(search_results_label)
        main_layout.addWidget(self.search_results_list, 1)  # 分配空间给搜索结果
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(line)
        
        # 下部文件浏览区域
        browse_label = QLabel("文件浏览:")
        main_layout.addWidget(browse_label)
        
        # 创建水平分割器 - 包含整个下部区域
        main_splitter = QSplitter(Qt.Horizontal)
        
        # 左侧: 文件夹列表
        folder_widget = QWidget()
        folder_layout = QVBoxLayout(folder_widget)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        
        folder_label = QLabel("文件夹列表:")
        self.folder_list = QListWidget()
        for folder in self.folders:
            self.folder_list.addItem(folder)
        
        self.folder_list.setCurrentRow(0)
        self.folder_list.currentRowChanged.connect(self.load_files)
        
        folder_layout.addWidget(folder_label)
        folder_layout.addWidget(self.folder_list)
        
        # 中部: 文件列表
        file_widget = QWidget()
        file_layout = QVBoxLayout(file_widget)
        file_layout.setContentsMargins(0, 0, 0, 0)
        
        file_label = QLabel("文件列表:")
        self.file_list = QListWidget()
        self.file_list.itemClicked.connect(self.file_selected)
        self.file_list.itemDoubleClicked.connect(self.open_file)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        self.open_button = QPushButton("打开文件")
        self.open_button.clicked.connect(self.open_file)
        self.delete_button = QPushButton("删除选中文件")
        self.delete_button.clicked.connect(self.delete_file)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.refresh_all)
        
        button_layout.addWidget(self.open_button)
        button_layout.addWidget(self.delete_button)
        button_layout.addWidget(self.refresh_button)
        
        file_layout.addWidget(file_label)
        file_layout.addWidget(self.file_list)
        file_layout.addLayout(button_layout)
        
        # 右侧: 文件内容预览
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        
        preview_label = QLabel("文件内容预览:")
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        preview_layout.addWidget(preview_label)
        preview_layout.addWidget(self.preview_text)
        
        # 为预览文本添加高亮器
        self.highlighter = WorkingDirectoryHighlighter(self.preview_text.document())
        
        # 添加部件到主分割器
        main_splitter.addWidget(folder_widget)
        main_splitter.addWidget(file_widget)
        main_splitter.addWidget(preview_widget)
        main_splitter.setSizes([200, 300, 700])  # 设置初始大小
        
        # 添加分割器到主布局
        main_layout.addWidget(main_splitter, 4)  # 分配更多空间给文件浏览区域
        
        # 加载所有文件
        self.load_all_files()
        
        # 加载初始文件夹的文件
        self.load_files()
    
    def file_selected(self, item):
        """当文件列表中选择文件时显示文件内容"""
        if not item:
            return
            
        current_folder_index = self.folder_list.currentRow()
        file_name = item.text()
        folder_path = self.folders[current_folder_index]
        file_path = os.path.join(folder_path, file_name)
        
        self.load_file_preview(file_path)
        
    def load_file_preview(self, file_path):
        """加载文件内容到预览面板"""
        self.preview_text.clear()
        
        try:
            if os.path.exists(file_path):
                # 使用plutil将二进制plist转换为XML格式
                result = subprocess.run(['plutil', '-convert', 'xml1', '-o', '-', file_path], 
                                      capture_output=True, text=True)
                
                if result.returncode == 0:
                    content = result.stdout
                else:
                    # 如果plutil命令失败，尝试直接读取文件
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                
                # 保留换行符以确保高亮器能够按行处理
                self.preview_text.setPlainText(content)
                
                # 手动查找并滚动到WorkingDirectory位置
                self._scroll_to_working_directory(self.preview_text)
            else:
                self.preview_text.setPlainText(f"文件不存在: {file_path}")
        except Exception as e:
            self.preview_text.setPlainText(f"无法读取文件内容: {str(e)}")
    
    def _scroll_to_working_directory(self, text_edit):
        """滚动到应用路径位置"""
        document = text_edit.document()
        cursor = text_edit.textCursor()
        
        # 从文档开始搜索应用路径
        content = document.toPlainText()
        
        # 查找的路径模式
        path_patterns = ['/Applications/', '/Application Support/']
        
        # 先尝试查找/Applications/
        for pattern in path_patterns:
            match_pos = content.find(pattern)
            if match_pos != -1:
                # 找到匹配位置，将光标移动到该位置
                cursor.setPosition(match_pos)
                text_edit.setTextCursor(cursor)
                
                # 确保找到的位置在视图中间
                text_edit.ensureCursorVisible()
                return True
        
        # 如果没有找到应用路径，尝试搜索WorkingDirectory
        working_dir_pos = content.find("<key>WorkingDirectory</key>")
        if working_dir_pos != -1:
            cursor.setPosition(working_dir_pos)
            text_edit.setTextCursor(cursor)
            text_edit.ensureCursorVisible()
            return True
            
        return False
    
    def open_file(self):
        """打开选中的文件"""
        # 检查是从搜索结果还是文件列表中选择的文件
        if self.search_results_list.hasFocus() and self.search_results_list.currentItem():
            result = self.search_results_list.currentItem().data(Qt.UserRole)
            if result:
                file_path = os.path.join(result.folder_path, result.file_name)
                self._show_file_content(file_path)
        elif self.file_list.currentItem():
            current_folder_index = self.folder_list.currentRow()
            file_name = self.file_list.currentItem().text()
            folder_path = self.folders[current_folder_index]
            file_path = os.path.join(folder_path, file_name)
            self._show_file_content(file_path)
        else:
            QMessageBox.information(self, "提示", "请先选择要打开的文件")
    
    def _show_file_content(self, file_path):
        """显示文件内容对话框"""
        try:
            if os.path.exists(file_path):
                dialog = FileContentDialog(file_path, self)
                dialog.exec_()
            else:
                QMessageBox.warning(self, "警告", f"文件不存在: {file_path}")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"打开文件时出错: {str(e)}")
    
    def load_all_files(self):
        """加载所有文件夹中的文件到内存中"""
        self.all_files = {}
        
        for folder_index, folder_path in enumerate(self.folders):
            self.all_files[folder_index] = {}
            
            try:
                if os.path.exists(folder_path):
                    files = os.listdir(folder_path)
                    for file in files:
                        if file.endswith('.plist'):
                            file_path = os.path.join(folder_path, file)
                            self.all_files[folder_index][file] = file_path
            except PermissionError:
                print(f"权限错误: 无法访问 {folder_path}")
    
    def search_files(self):
        """搜索所有文件夹中的文件"""
        search_term = self.search_input.text().lower()
        self.search_results_list.clear()
        
        if not search_term:
            return
        
        for folder_index, files_dict in self.all_files.items():
            folder_path = self.folders[folder_index]
            for file_name, file_path in files_dict.items():
                if search_term in file_name.lower():
                    result = SearchResult(file_name, folder_path, folder_index)
                    item = QListWidgetItem(str(result))
                    # 存储完整结果对象到item数据中
                    item.setData(Qt.UserRole, result)
                    self.search_results_list.addItem(item)
    
    def search_result_selected(self, item):
        """当搜索结果被选中时，跳转到对应的文件夹和文件"""
        result = item.data(Qt.UserRole)
        if result:
            # 选择对应的文件夹
            self.folder_list.setCurrentRow(result.folder_index)
            
            # 在文件列表中找到并选择对应的文件
            for i in range(self.file_list.count()):
                if self.file_list.item(i).text() == result.file_name:
                    self.file_list.setCurrentRow(i)
                    # 加载文件内容到预览面板
                    file_path = os.path.join(result.folder_path, result.file_name)
                    self.load_file_preview(file_path)
                    break
    
    def load_files(self):
        """加载选定文件夹中的文件到文件列表"""
        self.file_list.clear()
        self.preview_text.clear()  # 清空预览内容
        current_row = self.folder_list.currentRow()
        
        if current_row < 0 or current_row >= len(self.folders):
            return
        
        folder_path = self.folders[current_row]
        
        try:
            if os.path.exists(folder_path):
                files = os.listdir(folder_path)
                for file in files:
                    if file.endswith('.plist'):
                        self.file_list.addItem(file)
            else:
                QMessageBox.warning(self, "警告", f"文件夹不存在: {folder_path}")
        except PermissionError:
            QMessageBox.warning(self, "权限错误", f"没有权限访问: {folder_path}\n请以管理员身份运行此程序。")
    
    def refresh_all(self):
        """刷新所有数据"""
        self.load_all_files()
        self.load_files()
        self.search_input.clear()
        self.search_results_list.clear()
    
    def delete_file(self):
        """删除选中的文件"""
        current_folder_index = self.folder_list.currentRow()
        selected_items = self.file_list.selectedItems()
        
        if not selected_items:
            QMessageBox.information(self, "提示", "请先选择要删除的文件")
            return
        
        folder_path = self.folders[current_folder_index]
        
        # 确认删除
        reply = QMessageBox.question(self, "确认删除", 
                                    f"您确定要删除选中的 {len(selected_items)} 个文件吗？",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            success_count = 0
            error_messages = []
            
            for item in selected_items:
                file_path = os.path.join(folder_path, item.text())
                try:
                    if os.path.exists(file_path):
                        if os.access(file_path, os.W_OK):
                            os.remove(file_path)
                            success_count += 1
                        else:
                            error_messages.append(f"{item.text()}: 权限不足")
                    else:
                        error_messages.append(f"{item.text()}: 文件不存在")
                except Exception as e:
                    error_messages.append(f"{item.text()}: {str(e)}")
            
            # 刷新数据
            self.refresh_all()
            
            # 显示结果
            if success_count > 0:
                message = f"成功删除 {success_count} 个文件。"
                if error_messages:
                    message += f"\n\n删除失败的文件:\n" + "\n".join(error_messages)
                QMessageBox.information(self, "删除结果", message)
            else:
                QMessageBox.warning(self, "删除失败", "没有文件被删除。\n\n" + "\n".join(error_messages))

def main():
    app = QApplication(sys.argv)
    window = LaunchManager()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
