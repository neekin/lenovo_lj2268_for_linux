.PHONY: all install check clean
all:
	bash build-native.sh
install:
	bash install.sh
check: all
	python3 tests/selftest.py --library build/libjbigwrap.so --filter rastertolkpl
clean:
	rm -rf build
