.PHONY: all clean ko iolib

all: ko iolib

ko:
	$(MAKE) -C ko

iolib:
	$(MAKE) -C iolib

clean:
	$(MAKE) -C ko clean
	$(MAKE) -C iolib clean
