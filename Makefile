# Lenovo LJ2268 / LJ2268W  —— Linux 打印驱动 (LHPL 开源实现)
#
# 依赖:
#   编译: gcc + libjbig(头文件已随包提供 src/jbig.h, 链接库见下方自动探测)
#   运行: libjbig.so.0, poppler-utils(pdftoppm), cups
#
# 常用目标:
#   make                # 编译到 ./rastertolhpl (自动探测 libjbig 链接方式)
#   sudo make install   # 安装 filter + PPD 并重建 CUPS 队列 (需 root)
#   make test           # 打印测试页
#   make clean
#
# 覆盖参数:
#   make install DEVICE_URI="usb://Lenovo/LJ2268?serial=XXXX"
#   make install QUEUE=LJ2268 SYSTEMD=0      # 不装 cups 默认队列 / systemd 单元见 install.sh

CC      ?= gcc
CFLAGS  ?= -O2 -Wall
TARGET   = rastertolhpl
SRC      = src/rastertolhpl.c

CUPS_FILTER_DIR ?= /usr/lib/cups/filter
CUPS_MODEL_DIR  ?= /usr/share/cups/model
PPD              = ppd/LJ2268-lhpl.ppd
QUEUE           ?= Lenovo-LJ2268

# --- libjbig 链接方式自动探测 ------------------------------------------------
# 有 libjbig-dev  ->  -ljbig
# 只有运行时库    ->  直接链 libjbig.so.0 绝对路径 (Debian/Ubuntu 常见情形)
JBIG_LIB := $(shell printf 'int main(void){return 0;}' > .jbigtest.c; \
  if $(CC) .jbigtest.c -ljbig -o .jbigtest.out >/dev/null 2>&1; then \
    echo '-ljbig'; \
  else \
    ls /usr/lib/*/libjbig.so.0 /usr/lib/libjbig.so.0 /usr/lib64/libjbig.so.0 \
       /usr/local/lib/libjbig.so.0 2>/dev/null | head -1; \
  fi; rm -f .jbigtest.c .jbigtest.out)

# --- USB 设备 URI 自动探测 ---------------------------------------------------
DEVICE_URI ?= $(shell lpinfo -v 2>/dev/null \
  | awk '/^direct usb:\/\// {print $$NF}' \
  | grep -iE 'lenovo|lj2268' | head -1)

.PHONY: all install test clean check-deps

all: $(TARGET)

$(TARGET): $(SRC)
	@[ -n "$(JBIG_LIB)" ] || { \
	  echo "错误: 找不到 libjbig (既无 -ljbig 也无 libjbig.so.0)"; \
	  echo "请先安装: sudo apt install libjbig0"; exit 1; }
	$(CC) $(CFLAGS) -o $@ $< $(JBIG_LIB) -lm
	@echo "  链接方式: $(JBIG_LIB)"

install: check-deps $(TARGET)
	@[ -n "$(DEVICE_URI)" ] || { \
	  echo "错误: 未探测到打印机 USB 设备"; \
	  echo "  已接好 USB 的话, 手动指定:"; \
	  echo "    sudo make install DEVICE_URI=\"usb://Lenovo/LJ2268?serial=XXXX\""; \
	  echo "  可用设备列表: lpinfo -v | grep usb"; exit 1; }
	@if lpstat -a 2>/dev/null | awk '{print $$1}' | grep -qx "$(QUEUE)"; then \
	  echo "错误: 队列 '$(QUEUE)' 已存在, 为避免破坏现有配置已中止"; \
	  echo "  覆盖: sudo lpadmin -x $(QUEUE)   (或改用 install.sh --force)"; \
	  echo "  改名: sudo make install QUEUE=LJ2268"; exit 1; fi
	install -o root -g root -m 0755 $(TARGET) $(CUPS_FILTER_DIR)/$(TARGET)
	install -o root -g root -m 0644 $(PPD) $(CUPS_MODEL_DIR)/LJ2268-lhpl.ppd
	lpadmin -p $(QUEUE) -D "Lenovo LJ2268 (LHPL open driver)" -L "Home" \
	        -P $(CUPS_MODEL_DIR)/LJ2268-lhpl.ppd -v "$(DEVICE_URI)" -E 2>/dev/null
	cupsaccept $(QUEUE) 2>/dev/null || true
	cupsenable $(QUEUE) 2>/dev/null || true
	@# 默认打印机只在原本没有队列时才设, 已有环境不抢别人的默认
	@if [ "$$(lpstat -a 2>/dev/null | wc -l)" -le 1 ]; then \
	    lpadmin -d $(QUEUE); echo "  无其他队列, 已设为默认打印机"; \
	 else echo "  保留原有默认打印机 (需要改: sudo lpadmin -d $(QUEUE))"; fi
	@sleep 2
	@echo "=== 安装完成 ==="
	@echo "  设备: $(DEVICE_URI)"
	@lpstat -p $(QUEUE) 2>/dev/null || echo "  (队列刚建, 稍后再查: lpstat -p $(QUEUE))"
	@echo "打印测试: lp -d $(QUEUE) test/hello.pdf"
	@echo "局域网共享 / AirPrint 属于可选项, 用: sudo ./install.sh --airprint"

# 安装前置检查: 必须 root + 依赖齐备
check-deps:
	@[ "$$(id -u)" = 0 ] || { \
	  echo "错误: 需要 root (CUPS 拒绝执行非 root 拥有的 filter)"; \
	  echo "  请用: sudo make install"; exit 1; }
	@command -v lpadmin  >/dev/null || { echo "缺少 cups:          apt install cups"; exit 1; }
	@command -v pdftoppm >/dev/null || { echo "缺少 poppler-utils: apt install poppler-utils"; exit 1; }
	@echo "  依赖检查通过"

test:
	lp -d $(QUEUE) test/hello.pdf
	@sleep 15; lpstat -W completed | head -3

clean:
	rm -f $(TARGET) .jbigtest.c .jbigtest.out
