# `chezfiles`

```yaml
- type: chezfiles
  disable-service: false # (default: false), put true if you want the systemd services not to be enabled by default
  build: # this will only be applied at build step
    - common/system-build # files/chezfiles/common/build
  system: # this will only be applied on a running system (installed on a computer)
    - common/system-booted
  user: # this will only be applied for each user
    - common/user
```