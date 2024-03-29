# author: Le Anh Tai
# email: leanhtai01@gmail.com
# gitHub: https://github.com/leanhtai01
import json
import os
import pathlib
import re
import subprocess

from lib import diskutils, fileutils


class ArchInstall:
    def __init__(self, setting_file_name, live_system=True):
        self.load_settings(setting_file_name)
        self.home_dir = f'/home/{self.settings["username"]}'
        self.partition_layout = self.settings['partition_layout']
        self.live_system = live_system
        self.working_dir = (
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        self.pkg_info = (
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))) +
            '/packages_info/arch_linux'
        )

        if live_system:
            self.cmd_prefix = ['arch-chroot', '/mnt']
            self.path_prefix = '/mnt'
        else:
            self.cmd_prefix = ['sudo']
            self.path_prefix = ''

    def load_settings(self, file_name):
        """load setting from json file"""
        try:
            with open(file_name) as reader:
                self.settings = json.load(reader)
        except FileNotFoundError:
            self.settings = {}

    def install_packages(self, packages):
        """install packages"""
        subprocess.run(
            self.cmd_prefix
            + ['pacman', '-Syu', '--needed', '--noconfirm']
            + packages
        )

    def install_packages_asdeps(self, packages: list):
        """install packages asdeps"""
        subprocess.run(
            self.cmd_prefix +
            ['pacman', '-Syu', '--needed', '--noconfirm', '--asdeps'] +
            packages
        )

    def install_packages_from_file(self, file_name):
        """install packages from file contain packages list"""
        packages = self.get_packages_from_file(file_name)
        self.install_packages(packages)

    def disable_auto_generate_mirrorlist(self):
        """make sure mirrorlist not auto generated"""
        subprocess.run(['systemctl', 'disable', 'reflector.service'])
        subprocess.run(['systemctl', 'disable', 'reflector.timer'])
        subprocess.run(['systemctl', 'stop', 'reflector.service'])
        subprocess.run(['systemctl', 'stop', 'reflector.timer'])

    def connect_to_wifi(self):
        """connect to wifi using iwd"""
        subprocess.run([
            'iwctl',
            f'--passphrase={self.settings["wifi_password"]}',
            'station', f'{self.settings["wifi_device"]}',
            'connect-hidden' if self.settings["is_hidden_wifi"] else 'connect',
            f'{self.settings["wifi_ssid"]}'
        ])

    def update_system_clock(self):
        """update system clock from internet"""
        subprocess.run(['timedatectl', 'set-ntp', 'true'])

    def setup_mirrors(self):
        """setup mirrors"""
        with open('/etc/pacman.d/mirrorlist', 'w') as writer:
            for mirror in self.settings['mirrors']:
                writer.write(mirror + '\n')

    def prepare_disk(self):
        """prepare disk for installation"""
        device = self.settings['device_to_install']
        esp_size = self.settings['size_of_efi_partition']
        boot_size = self.settings['size_of_boot_partition']
        swap_size = self.settings['size_of_swap_partition']
        root_size = self.settings['size_of_root_partition']
        layout = self.settings['partition_layout']
        is_dual_boot = self.settings['is_dual_boot_windows']
        password = self.settings['system_partition_password']

        if layout == 'unencrypted':
            if is_dual_boot:
                partnames = diskutils.prepare_unencrypted_dual_boot_layout(
                    device, boot_size, swap_size, root_size
                )
            else:
                partnames = diskutils.prepare_unencrypted_layout(
                    device, esp_size, boot_size, swap_size
                )
        elif layout == 'encrypted':
            if is_dual_boot:
                partnames = diskutils.prepare_encrypted_dual_boot_layout(
                    device, password, boot_size, swap_size, root_size
                )
            else:
                partnames = diskutils.prepare_encrypted_layout(
                    device, password, esp_size, boot_size, swap_size
                )

        self.settings.update(partnames)

        # save new info to settings.json
        with open('settings.json', 'w') as writer:
            json.dump(self.settings, writer, indent=4)

    def install_essential_packages(self):
        """install essential packages using pacstrap"""
        packages = [
            'base',
            'base-devel',
            'linux',
            'linux-headers',
            'linux-firmware',
            'man-pages',
            'man-db',
            'iptables-nft'
        ]

        subprocess.run(['pacstrap', '/mnt'] + packages)

    def configure_fstab(self):
        """configure fstab"""
        subprocess.run('genfstab -U /mnt >> /mnt/etc/fstab', shell=True)

    def configure_time_zone(self):
        """configure time zone"""
        subprocess.run(self.cmd_prefix + [
            'ln', '-sf',
            '/usr/share/zoneinfo/Asia/Ho_Chi_Minh', '/etc/localtime'
        ])

        subprocess.run(self.cmd_prefix + [
            'hwclock', '--systohc'
        ])

    def configure_localization(self):
        """configure localization"""
        locale_gen_path = '/mnt/etc/locale.gen'

        fileutils.backup(locale_gen_path)

        with open(locale_gen_path, 'w') as locale_gen_file:
            locale_gen_file.write('en_US.UTF-8 UTF-8' + '\n')

        subprocess.run(self.cmd_prefix + ['locale-gen'])

        with open('/mnt/etc/locale.conf', 'w') as locale_conf_file:
            locale_conf_file.write('LANG=en_US.UTF-8' + '\n')

    def enable_multilib(self):
        """enable multilib"""
        pacman_conf_path = '/mnt/etc/pacman.conf'

        fileutils.backup(pacman_conf_path)

        with open(pacman_conf_path) as reader:
            content = reader.readlines()

        # find the first line contain multilib config
        line_number = content.index('#[multilib]\n')

        # comment out 2 lines contain multilib config
        content[line_number] = content[line_number].replace('#', '')
        line_number += 1  # to comment next line
        content[line_number] = content[line_number].replace('#', '')

        # save changes
        with open(pacman_conf_path, 'w') as writer:
            writer.writelines(content)

    def configure_network(self):
        """configure network"""
        hostname = self.settings['hostname']

        with open('/mnt/etc/hostname', 'w') as hostname_file:
            hostname_file.write(f'{hostname}\n')

        with open('/mnt/etc/hosts', 'a') as hosts_file:
            hosts_file.write('127.0.0.1\tlocalhost\n')
            hosts_file.write('::1\tlocalhost\n')
            hosts_file.write(
                f'127.0.1.1\t{hostname}.localdomain\t{hostname}\n'
            )

        subprocess.run(self.cmd_prefix + [
            'pacman', '-Syu', '--needed', '--noconfirm', 'networkmanager'
        ])

        subprocess.run(self.cmd_prefix + [
            'systemctl', 'enable', 'NetworkManager'
        ])

    def set_root_password(self):
        """setup root password"""
        password = (self.settings['root_password'] + '\n') * 2
        subprocess.run(self.cmd_prefix + ['passwd'], input=password.encode())

    def add_normal_user(self):
        """add normal user"""
        real_name = self.settings['user_real_name']
        username = self.settings['username']
        password = (self.settings['user_password'] + '\n') * 2
        user_groups = self.settings['user_groups']

        subprocess.run(self.cmd_prefix + [
            'useradd',
            '-G', ','.join(user_groups),
            '-s', '/bin/bash',
            '-m', f'{username}',
            '-d', f'/home/{username}',
            '-c', f'{real_name}'
        ])

        subprocess.run(
            self.cmd_prefix + ['passwd', f'{username}'],
            input=password.encode()
        )

    def allow_user_in_wheel_group_execute_any_command(self):
        """allow user in wheel group execute any command"""
        sudoers_path = '/mnt/etc/sudoers'

        fileutils.backup(sudoers_path)

        fileutils.multiple_replace_in_line(
            sudoers_path,
            rf'^{re.escape("# %wheel ALL=(ALL:ALL) ALL")}.*',
            [('# ', '')]
        )

    def disable_sudo_password_prompt_timeout(self):
        """disable sudo password prompt timeout"""
        sudoers_path = '/mnt/etc/sudoers'

        fileutils.backup(sudoers_path)

        with open(sudoers_path, 'a') as writer:
            writer.write('\n## Disable password prompt timeout\n')
            writer.write('Defaults passwd_timeout=0\n')

    def increase_sudo_timestamp_timeout(self):
        """reduce the number of times re-enter password using sudo"""
        sudoers_path = '/mnt/etc/sudoers'

        fileutils.backup(sudoers_path)

        with open(sudoers_path, 'a') as writer:
            writer.write('\n## Set sudo timestamp timeout\n')
            writer.write(
                'Defaults timestamp_timeout=' +
                f'{self.settings["timeout_for_sudo"]}\n'
            )

    def configure_mkinitcpio_for_encrypted_system(self):
        """configure mkinitcpio for encrypted system"""
        # make sure lvm2 is installed
        self.install_packages(['lvm2'])

        mkinitcpio_config_file = '/mnt/etc/mkinitcpio.conf'

        fileutils.backup(mkinitcpio_config_file)

        fileutils.multiple_replace_in_line(
            mkinitcpio_config_file,
            rf'^{re.escape("HOOKS")}.*',
            [
                (' keyboard', ''),
                ('autodetect', 'autodetect keyboard keymap'),
                ('block', 'block encrypt lvm2')
            ]
        )

        self.build_initramfs_image_mkinitcpio()

    def configure_mkinitcpio_for_hibernation(self):
        """configure mkinitcpio for hibernation"""
        mkinitcpio_config_path = '/mnt/etc/mkinitcpio.conf'

        fileutils.backup(mkinitcpio_config_path)

        fileutils.multiple_replace_in_line(
            mkinitcpio_config_path,
            rf'^{re.escape("HOOKS")}.*',
            [('filesystems', 'filesystems resume')]
        )

        self.build_initramfs_image_mkinitcpio()

    def build_initramfs_image_mkinitcpio(self):
        """build initramfs image(s) according to specified preset"""
        subprocess.run(self.cmd_prefix + [
            'mkinitcpio', '-p', 'linux'
        ])

    def get_uuid(self, partition):
        """get partition's UUID"""
        output = subprocess.run(self.cmd_prefix + [
            'blkid', '-s', 'UUID', '-o', 'value', f'/dev/{partition}'
        ], capture_output=True)

        uuid = output.stdout.decode().strip()

        return uuid

    def configure_systemd_bootloader(self):
        """configure systemd bootloader"""
        self.install_packages(['efibootmgr', 'intel-ucode'])

        subprocess.run(self.cmd_prefix + [
            'bootctl', '--esp-path=/efi', '--boot-path=/boot', 'install'
        ])

        loader_conf_path = '/mnt/efi/loader/loader.conf'
        with open(loader_conf_path, 'w') as loader_conf_file:
            loader_conf_file.write('default archlinux\n')
            loader_conf_file.write('timeout 5\n')
            loader_conf_file.write('console-mode keep\n')
            loader_conf_file.write('editor no\n')

        if self.partition_layout == 'unencrypted':
            root_uuid = self.get_uuid(self.settings['root_part_name'])
            swap_uuid = self.get_uuid(self.settings['swap_part_name'])
        elif self.partition_layout == 'encrypted':
            luks_part_name = self.settings['luks_encrypted_part_name']
            mapper_name = self.settings['luks_mapper_name']
            vg_name = self.settings['vg_name']
            lv_swap_name = self.settings['lv_swap_name']
            lv_root_name = self.settings['lv_root_name']

            luks_uuid = self.get_uuid(luks_part_name)
            lv_swap_uuid = self.get_uuid(f'{vg_name}/{lv_swap_name}')

        archlinux_conf_path = '/mnt/boot/loader/entries/archlinux.conf'
        with open(archlinux_conf_path, 'w') as archlinux_conf_file:
            archlinux_conf_file.write('title Arch Linux\n')
            archlinux_conf_file.write('linux /vmlinuz-linux\n')
            archlinux_conf_file.write('initrd /intel-ucode.img\n')
            archlinux_conf_file.write('initrd /initramfs-linux.img\n')
            if self.partition_layout == 'unencrypted':
                archlinux_conf_file.write(
                    f'options root=UUID={root_uuid} ' +
                    f'resume=UUID={swap_uuid} rw\n'
                )
            elif self.partition_layout == 'encrypted':
                archlinux_conf_file.write(
                    f'options cryptdevice=UUID={luks_uuid}:{mapper_name}' +
                    f' root=/dev/{vg_name}/{lv_root_name} ' +
                    f'resume=UUID={lv_swap_uuid} rw\n'
                )

    def get_packages_from_file(self, file_path):
        """get packages from file"""
        with open(file_path) as reader:
            packages = reader.read()

        return packages.splitlines()

    def install_intel_drivers(self):
        """install gpu drivers"""
        self.install_packages_from_file(f'{self.pkg_info}/intel.txt')

    def install_other_packages(self):
        """install other packages"""
        self.install_packages_from_file(f'{self.pkg_info}/other.txt')

    def install_gnome_de(self):
        """install GNOME DE"""
        self.install_packages_from_file(f'{self.pkg_info}/gnome_de.txt')

        # package to install GNOME extensions from browser
        if not self.is_package_installed('gnome-browser-connector'):
            self.install_aur_packages(['gnome-browser-connector'])

        # GNOME extensions display hardware's information
        if not self.is_package_installed('gnome-shell-extension-vitals-git'):
            self.install_aur_packages(['gnome-shell-extension-vitals-git'])

    def install_kde_plasma_de(self):
        """install KDE Plasma DE"""
        self.install_packages_from_file(f'{self.pkg_info}/kde_plasma_de.txt')

    def install_desktop_environment(self):
        """install desktop environment based on user settings"""
        de = self.settings['desktop_environment']

        if de == 'GNOME':
            self.install_gnome_de()
        elif de == 'Plasma':
            self.install_kde_plasma_de()

    def enable_bluetooth_service(self):
        """enable bluetooth service"""
        subprocess.run(self.cmd_prefix + [
            'systemctl', 'enable', 'bluetooth'
        ])

    def configure_display_manager(self):
        """configure display manager"""
        de = self.settings['desktop_environment']

        if de == 'GNOME':
            subprocess.run(self.cmd_prefix + [
                'systemctl', 'enable', 'gdm'
            ])
        elif de == 'Plasma':
            subprocess.run(self.cmd_prefix + [
                'systemctl', 'enable', 'sddm'
            ])

    def install_fonts(self):
        """install fonts"""
        self.install_packages_from_file(f'{self.pkg_info}/fonts.txt')

    def install_browsers(self):
        """install browsers"""
        self.install_packages_from_file(f'{self.pkg_info}/browsers.txt')

    def install_core_programming(self):
        """install core programming packages"""
        self.install_packages_from_file(
            f'{self.pkg_info}/core_programming.txt'
        )

    def install_core_tools(self):
        """install core tools"""
        self.install_packages_from_file(f'{self.pkg_info}/core_tools.txt')

    def install_editors(self):
        """install editors"""
        self.install_packages_from_file(f'{self.pkg_info}/editors.txt')

    def install_virtualbox(self):
        """install virtualbox"""
        self.install_packages([
            'virtualbox', 'virtualbox-guest-iso', 'virtualbox-host-dkms'
        ])

        subprocess.run(self.cmd_prefix + [
            'gpasswd', '-a', f'{self.settings["username"]}', 'vboxusers'
        ])

        self.install_aur_packages(['virtualbox-ext-oracle'])

    def systemctl_enable(self, unit: str):
        """enable unit using systemctl"""
        subprocess.run(self.cmd_prefix + [
            'systemctl', 'enable', unit
        ])

    def systemctl_start(self, unit: str):
        """start unit using systemctl"""
        subprocess.run(self.cmd_prefix + [
            'systemctl', 'start', unit
        ])

    def install_docker(self):
        """install docker"""
        self.install_packages(['docker', 'docker-compose'])

        subprocess.run(self.cmd_prefix + [
            'gpasswd', '-a', f'{self.settings["username"]}', 'docker'
        ])

        self.systemctl_enable('docker.service')
        self.systemctl_start('docker.service')

    def install_c_cpp_programming(self):
        """install C, C++ programming"""
        self.install_packages_from_file(
            f'{self.pkg_info}/c_cpp_programming.txt')

    def install_go_programming(self):
        """install Go programming"""
        self.install_packages_from_file(f'{self.pkg_info}/go_programming.txt')

    def install_java_programming(self):
        """install java programming"""
        self.install_packages_from_file(
            f'{self.pkg_info}/java_programming.txt')

    def install_dotnet_programming(self):
        """install dotnet programming"""
        self.install_packages_from_file(
            f'{self.pkg_info}/dotnet_programming.txt')

    def install_python_programming(self):
        """install python programming"""
        self.install_packages_from_file(
            f'{self.pkg_info}/python_programming.txt')

    def install_javascript_programming(self):
        """install javascript programming"""
        self.install_packages_from_file(
            f'{self.pkg_info}/javascript_programming.txt'
        )

    def install_gnome_programming(self):
        """install GNOME programming"""
        if self.settings['desktop_environment'] != 'GNOME':
            return

        self.install_packages_from_file(
            f'{self.pkg_info}/gnome_programming.txt'
        )

    def install_multimedia(self):
        """install multimedia"""
        self.install_packages_from_file(f'{self.pkg_info}/multimedia.txt')

    def install_office(self):
        """install office"""
        self.install_packages_from_file(f'{self.pkg_info}/office.txt')

    def configure_as_virtualbox_guest(self):
        """configure as VirtualBox guest"""
        self.install_packages(['virtualbox-guest-utils'])

        subprocess.run(self.cmd_prefix + [
            'systemctl', 'enable', 'vboxservice'
        ])

        subprocess.run(self.cmd_prefix + [
            'gpasswd', '-a', f'{self.settings["username"]}', 'vboxsf'
        ])

    def get_gnome_custom_shortcut_indexes(self):
        """get GNOME custom shortcut indexes"""
        SCHEMA_TO_LIST = 'org.gnome.settings-daemon.plugins.media-keys'

        output = subprocess.run([
            'gsettings', 'get', f'{SCHEMA_TO_LIST}', 'custom-keybindings'
        ], capture_output=True)

        path_list = output.stdout.decode()

        if path_list.strip() == '@as []':
            indexes = []
        else:
            indexes = re.findall(r'\d+', path_list)

        return path_list, indexes

    def add_gnome_shortcut(self, name, key_binding, command):
        """add a GNOME shortcut"""
        SCHEMA_TO_LIST = 'org.gnome.settings-daemon.plugins.media-keys'
        SCHEMA_TO_ITEM = (
            'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding'
        )
        PATH_TO_CUSTOM_KEY = (
            '/org/gnome/settings-daemon/plugins/media-keys'
            '/custom-keybindings/custom'
        )

        path_list, indexes = self.get_gnome_custom_shortcut_indexes()
        index = len(indexes)

        subprocess.run([
            'gsettings', 'set',
            f'{SCHEMA_TO_ITEM}:{PATH_TO_CUSTOM_KEY}{index}/',
            'name', f'"{name}"'
        ])

        subprocess.run([
            'gsettings', 'set',
            f'{SCHEMA_TO_ITEM}:{PATH_TO_CUSTOM_KEY}{index}/',
            'binding', f'"{key_binding}"'
        ])

        subprocess.run([
            'gsettings', 'set',
            f'{SCHEMA_TO_ITEM}:{PATH_TO_CUSTOM_KEY}{index}/',
            'command', f'"{command}"'
        ])

        # determine new path_list
        if index == 0:
            path_list = f"['{PATH_TO_CUSTOM_KEY}{index}/']"
        else:
            # -2 here mean ignore the last character ] in old path_list
            path_list = path_list[:-2] + f", '{PATH_TO_CUSTOM_KEY}{index}/']"

        subprocess.run([
            'gsettings', 'set', f'{SCHEMA_TO_LIST}',
            'custom-keybindings', f'{path_list}'
        ])

    def clear_all_gnome_custom_shortcuts(self):
        """clear all GNOME custom shortcuts"""
        SCHEMA_TO_LIST = 'org.gnome.settings-daemon.plugins.media-keys'
        SCHEMA_TO_ITEM = (
            'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding'
        )
        PATH_TO_CUSTOM_KEY = (
            '/org/gnome/settings-daemon/plugins/media-keys'
            '/custom-keybindings/custom'
        )

        indexes = self.get_gnome_custom_shortcut_indexes()[1]

        for index in indexes:
            subprocess.run([
                'gsettings', 'reset',
                f'{SCHEMA_TO_ITEM}:{PATH_TO_CUSTOM_KEY}{index}/',
                'name'
            ])

            subprocess.run([
                'gsettings', 'reset',
                f'{SCHEMA_TO_ITEM}:{PATH_TO_CUSTOM_KEY}{index}/',
                'binding'
            ])

            subprocess.run([
                'gsettings', 'reset',
                f'{SCHEMA_TO_ITEM}:{PATH_TO_CUSTOM_KEY}{index}/',
                'command'
            ])

        subprocess.run([
            'gsettings', 'reset', f'{SCHEMA_TO_LIST}',
            'custom-keybindings'
        ])

    def make_gnome_shortcuts(self):
        """make some GNOME shortcuts for frequently program"""
        if self.settings['desktop_environment'] != 'GNOME':
            return

        self.clear_all_gnome_custom_shortcuts()

        if self.is_package_installed('nautilus'):
            self.add_gnome_shortcut(
                'Nautilus', '<Super>e', 'nautilus'
            )

        if self.is_package_installed('gnome-terminal'):
            self.add_gnome_shortcut(
                'GNOME Terminal', '<Primary><Alt>t', 'gnome-terminal'
            )

        if self.is_package_installed('krusader'):
            self.add_gnome_shortcut(
                'Emacs', '<Primary><Alt>k', 'krusader'
            )

        if self.is_package_installed('emacs'):
            self.add_gnome_shortcut(
                'Emacs', '<Primary><Alt>e', 'emacs'
            )

        if self.is_package_installed('google-chrome'):
            self.add_gnome_shortcut(
                'Google Chrome', '<Primary><Alt>c', 'google-chrome-stable'
            )

        if self.is_package_installed('firefox-developer-edition'):
            self.add_gnome_shortcut(
                'Firefox Developer Edition',
                '<Primary><Alt>f',
                'firefox-developer-edition'
            )

        if self.is_package_installed('keepassxc'):
            self.add_gnome_shortcut(
                'KeePassXC',
                '<Primary><Alt>p',
                'keepassxc'
            )

    def is_package_installed(self, package_name):
        """check whether package is installed"""
        username = self.settings['username']
        cmd_prefix = (['arch-chroot', '-u', f'{username}', '/mnt']
                      if self.live_system
                      else [])

        cmd_result = subprocess.run(cmd_prefix + [
            'pacman', '-Qi', package_name
        ], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

        return True if cmd_result.returncode == 0 else False

    def is_flatpak_package_installed(self, package_id):
        """check whether flatpak package is installed"""
        if not self.is_package_installed('flatpak'):
            return False

        cmd_result = subprocess.run([
            'flatpak', 'info', package_id
        ], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

        return True if cmd_result.returncode == 0 else False

    def install_pipewire(self):
        """configure sound server"""
        self.install_packages_from_file(f'{self.pkg_info}/pipewire.txt')

        username = self.settings['username']
        cmd_prefix = (f'arch-chroot -u {username} /mnt '
                      if self.live_system
                      else '')

        subprocess.run(
            self.working_dir +
            f'/bash/configure_pipewire.sh "{username}" "{cmd_prefix}"',
            shell=True
        )

    def install_nvm(self):
        """install nvm"""
        self.install_aur_packages(['nvm'])
        subprocess.run(
            "echo 'source /usr/share/nvm/init-nvm.sh' >> " +
            f"{self.path_prefix}/{self.home_dir}/.bashrc", shell=True)

        if self.live_system:
            username = self.settings['username']

            subprocess.run(self.cmd_prefix + [
                'chown', f'{username}:{username}',
                f'/home/{username}/.bashrc'
            ])

    def configure_git(self):
        """configure git"""
        # make sure git is installed before configure
        if not self.is_package_installed('git'):
            self.install_packages(['git'])

        subprocess.run(
            f'cp {self.working_dir}/resources/' +
            '.gitconfig* ' +
            f'{self.path_prefix}/{self.home_dir}',
            shell=True
        )

        if self.live_system:
            username = self.settings['username']

            subprocess.run(self.cmd_prefix + [
                'chown', f'{username}:{username}',
                f'/home/{username}/.gitconfig'
            ])

            subprocess.run(self.cmd_prefix + [
                'chown', f'{username}:{username}',
                f'/home/{username}/.gitconfig-personal.conf'
            ])

            subprocess.run(self.cmd_prefix + [
                'chown', f'{username}:{username}',
                f'/home/{username}/.gitconfig-work.conf'
            ])

    def install_yay_aur_helper(self):
        """install Yay AUR helper"""
        username = self.settings['username']
        password = self.settings['user_password']
        cmd_prefix = (f'arch-chroot -u {username} /mnt '
                      if self.live_system
                      else '')

        subprocess.run(
            self.working_dir +
            f'/bash/install_yay.sh "{username}" "{cmd_prefix}" "{password}"',
            shell=True
        )

    def install_aur_packages(self, packages):
        """install packages from AUR"""
        # make sure Yay is installed
        if not self.is_package_installed('yay'):
            self.install_yay_aur_helper()

        # remove installed packages from list
        packages = list(
            filter(
                lambda package: not self.is_package_installed(package),
                packages
            )
        )

        if packages:
            username = self.settings['username']
            password = self.settings['user_password']
            cmd_prefix = (f'arch-chroot -u {username} /mnt '
                          if self.live_system
                          else '')
            packages = ' '.join(packages)

            subprocess.run(
                self.working_dir +
                f'/bash/install_aur_packages.sh ' +
                f'"{username}" "{cmd_prefix}" "{password}" "{packages}"',
                shell=True
            )

            if self.live_system:
                if os.path.ismount('/mnt/dev'):
                    subprocess.run('umount /mnt/dev', shell=True)

                if os.path.ismount('/mnt/tmp'):
                    subprocess.run('umount /mnt/tmp', shell=True)

    def install_aur_packages_from_file(self, file_name):
        """install AUR packages from file contain packages list"""
        packages = self.get_packages_from_file(file_name)
        self.install_aur_packages(packages)

    def install_disc_image_tools(self):
        """install disc image tools"""
        self.install_packages(
            ['cdrtools', 'libcdio', 'cdemu-client', 'vhba-module-dkms']
        )

        subprocess.run(self.cmd_prefix + [
            'modprobe', '-a', 'sg', 'sr_mod', 'vhba'
        ])

        self.install_aur_packages(['gcdemu'])

    def install_packettracer(self):
        """install Packet Tracer"""
        self.install_aur_packages(['packettracer'])

        subprocess.run(
            f'cp {self.working_dir}/local_repos/' +
            'arch_linux/CiscoPacketTracer* ' +
            f'{self.path_prefix}/{self.home_dir}/.cache/yay/packettracer',
            shell=True
        )

        if self.live_system:
            username = self.settings['username']

            subprocess.run(self.cmd_prefix + [
                'chown', '-R', f'{username}:{username}',
                f'/home/{username}/.cache/yay/packettracer/'
            ])

        self.install_aur_packages(['packettracer'])

    def install_flatpak_packages(self, package_ids):
        """install packages flatpak"""
        if not self.is_package_installed('flatpak'):
            self.install_packages(['flatpak'])

        subprocess.run(['flatpak', 'update', '-y'])

        for package_id in package_ids:
            if not self.is_flatpak_package_installed(package_id):
                subprocess.run([
                    'flatpak', 'install', package_id, '-y'
                ])

    def install_flatpak_packages_from_file(self, file_name):
        """install flatpak packages from file"""
        package_ids = self.get_packages_from_file(file_name)
        self.install_flatpak_packages(package_ids)

    def install_kvm(self):
        """install KVM"""
        self.install_packages_from_file(f'{self.pkg_info}/kvm.txt')

        subprocess.run(self.cmd_prefix + [
            'systemctl', 'enable', 'libvirtd'
        ])

        libvirtd_conf_path = self.path_prefix + '/etc/libvirt/libvirtd.conf'
        fileutils.backup(libvirtd_conf_path)

        fileutils.multiple_replace_in_line(
            libvirtd_conf_path,
            rf'^{re.escape("#unix_sock_group = ")}.*',
            [('#', '')]
        )

        fileutils.multiple_replace_in_line(
            libvirtd_conf_path,
            rf'^{re.escape("#unix_sock_rw_perms = ")}.*',
            [('#', '')]
        )

        username = self.settings['username']

        subprocess.run(self.cmd_prefix + [
            'gpasswd', '-a', username, 'libvirt'
        ])

        subprocess.run(self.cmd_prefix + [
            'gpasswd', '-a', username, 'kvm'
        ])

    def gnome_gsettings_set(self, schema, key, value):
        """sets the value of KEY to VALUE"""
        subprocess.run([
            'gsettings', 'set', f'{schema}', f'{key}', f'{value}'
        ])

    def configure_gnome(self):
        """configure GNOME"""
        if self.settings['desktop_environment'] != 'GNOME':
            return

        # set default monospace font
        if not self.is_package_installed('ttf-cascadia-code'):
            self.install_packages(['ttf-cascadia-code'])
        self.gnome_gsettings_set(
            'org.gnome.desktop.interface',
            'monospace-font-name',
            'Cascadia Mono 12'
        )

        # set default interface font
        self.gnome_gsettings_set(
            'org.gnome.desktop.interface',
            'font-name',
            'Cascadia Mono 12'
        )

        # set default legacy windows titles font
        self.gnome_gsettings_set(
            'org.gnome.desktop.wm.preferences',
            'titlebar-font',
            'Cascadia Mono Bold 12'
        )

        # set default document font
        self.gnome_gsettings_set(
            'org.gnome.desktop.interface',
            'document-font-name',
            'Cascadia Mono 12'
        )

        # set font-antialiasing to rgba
        self.gnome_gsettings_set(
            'org.gnome.desktop.interface',
            'font-antialiasing',
            'rgba'
        )

        # switch applications only in current workspace
        self.gnome_gsettings_set(
            'org.gnome.shell.app-switcher',
            'current-workspace-only',
            'true'
        )

        # schedule Night Light
        self.gnome_gsettings_set(
            'org.gnome.settings-daemon.plugins.color',
            'night-light-enabled',
            'true'
        )
        self.gnome_gsettings_set(
            'org.gnome.settings-daemon.plugins.color',
            'night-light-schedule-from',
            '18.0'
        )

        # show weekday
        self.gnome_gsettings_set(
            'org.gnome.desktop.interface',
            'clock-show-weekday',
            'true'
        )

        # empty favorite-apps
        self.gnome_gsettings_set(
            'org.gnome.shell',
            'favorite-apps',
            '[]'
        )

        # set default folder viewer nautilus
        self.gnome_gsettings_set(
            'org.gnome.nautilus.preferences',
            'default-folder-viewer',
            'list-view'
        )

        # set default-zoom-level nautilus
        self.gnome_gsettings_set(
            'org.gnome.nautilus.list-view',
            'default-zoom-level',
            'large'
        )

        # disable suspend
        self.gnome_gsettings_set(
            'org.gnome.settings-daemon.plugins.power',
            'sleep-inactive-battery-type',
            'nothing'
        )
        self.gnome_gsettings_set(
            'org.gnome.settings-daemon.plugins.power',
            'sleep-inactive-ac-type',
            'nothing'
        )

        # turn off dim screen
        self.gnome_gsettings_set(
            'org.gnome.settings-daemon.plugins.power',
            'idle-dim',
            'false'
        )

        # turn off screen blank
        self.gnome_gsettings_set(
            'org.gnome.desktop.session',
            'idle-delay',
            'uint32 0'
        )

        # show battery percentage
        self.gnome_gsettings_set(
            'org.gnome.desktop.interface',
            'show-battery-percentage',
            'true'
        )

        # set theme to dark
        self.gnome_gsettings_set(
            'org.gnome.desktop.interface',
            'color-scheme',
            'prefer-dark'
        )

    def configure_auto_mount_luks_encrypted_devices(self):
        """configure auto mount LUKS encrypted devices"""
        path_prefix = '/' if self.path_prefix == '' else self.path_prefix

        # create directory contain LUKS passwords
        luks_keys_dir_name = 'luks-keys'
        luks_keys_dir = os.path.join(
            path_prefix, f'etc/{luks_keys_dir_name}'
        )
        pathlib.Path(luks_keys_dir).mkdir(exist_ok=True)

        # secure the luks-passwords directory
        subprocess.run(['chmod', '600', luks_keys_dir])

        devices = self.settings['luks_encrypted_devices']
        username = self.settings['username']
        for device in devices:
            part_uuid = device['part_uuid']
            mapper_uuid = device['mapper_uuid']
            mount_point_name = device['mount_point_name']
            key = device['key']

            # write key to file
            path_to_keyfile = os.path.join(luks_keys_dir, f'{part_uuid}')
            with open(path_to_keyfile, 'w') as keyfile_writer:
                keyfile_writer.write(key)

            # write encryption information to crypttab
            path_to_crypttab = os.path.join(path_prefix, 'etc/crypttab')
            fileutils.backup(path_to_crypttab)
            with open(path_to_crypttab, 'a') as crypttab_writer:
                crypttab_writer.write(
                    f'luks-{part_uuid}\t' +
                    f'UUID={part_uuid}\t' +
                    f'/etc/{luks_keys_dir_name}/{part_uuid}\t' +
                    'nofail\n\n'
                )

            # write mount information to fstab
            path_to_fstab = os.path.join(path_prefix, 'etc/fstab')
            fileutils.backup(path_to_fstab)
            with open(path_to_fstab, 'a') as fstab_writer:
                fstab_writer.write(
                    f'/dev/disk/by-uuid/{mapper_uuid}\t' +
                    f'/run/media/{username}/{mount_point_name}\t' +
                    'auto\t' +
                    'nosuid,nodev,nofail,x-gvfs-show,' +
                    'x-systemd.before=httpd.service\t' +
                    '0\t0\n\n'
                )

    def get_optional_deps(self, package_name):
        """get package optional dependencies"""
        if not self.is_package_installed(package_name):
            return []

        output = subprocess.run(self.cmd_prefix + [
            'pacman', '-Qi', package_name
        ], capture_output=True)
        package_info = output.stdout.decode()

        match = re.search(
            r'Optional Deps.*Required By', package_info, re.DOTALL
        )

        raw_opt_pkg_info = match.group(0)

        raw_opt_pkg_info = re.sub(r'Optional Deps\s*:', '', raw_opt_pkg_info)
        raw_opt_pkg_info = re.sub(r'Required By.*', '', raw_opt_pkg_info)
        lines = raw_opt_pkg_info.splitlines()

        optional_pkg_gen = map(
            lambda line: (line.split(':')[0].strip()
                          if ':' in line
                          else line.split()[0].strip()),
            lines
        )
        optional_pkgs = list(optional_pkg_gen)

        return optional_pkgs

    def get_non_required_optional_deps(self, package_name: str):
        """get non-required optional dependencies of package"""
        optional_deps = self.get_optional_deps(package_name)
        non_required_optional_deps = []

        for pkg in optional_deps:
            if not self.is_required(pkg):
                non_required_optional_deps.append(pkg)

        return non_required_optional_deps

    def install_packages_with_all_optional_deps(self, packages: list):
        """install packages with all optional dependencies"""
        # install packages
        self.install_packages(packages)

        # install optional dependencies
        for package in packages:
            self.install_packages_asdeps(
                self.get_optional_deps(package)
            )

    def is_required(self, package_name):
        """check whether package is required by other package(s)"""
        output = subprocess.run([
            'pacman', '-Qi', package_name
        ], capture_output=True)
        package_info = output.stdout.decode()

        match = re.search(
            r'^Required By\s*:\s*None$',
            package_info,
            re.MULTILINE
        )

        return False if match else True

    def install_tlp(self):
        """install TLP"""
        self.install_packages(['tlp'])

        subprocess.run(self.cmd_prefix + [
            'systemctl', 'enable', 'tlp'
        ])

        subprocess.run(self.cmd_prefix + [
            'systemctl', 'start', 'tlp'
        ])

    def install_games(self):
        """install games"""
        self.install_packages_with_all_optional_deps(
            ['lutris', 'wine', 'winetricks']
        )

        self.install_packages_from_file(
            f'{self.pkg_info}/games.txt'
        )

    def configure_ibus_bamboo(self):
        """configure ibus-bamboo"""
        if not self.is_package_installed('ibus-bamboo'):
            self.install_aur_packages(['ibus-bamboo'])

        self.gnome_gsettings_set(
            'org.gnome.desktop.input-sources',
            'sources',
            "[('xkb', 'us'), ('ibus', 'Bamboo')]"
        )

        self.gnome_gsettings_set(
            'org.gnome.desktop.input-sources',
            'per-window',
            'true'
        )

    def configure_thermald(self):
        """configure thermald"""
        if not self.is_package_installed('thermald'):
            self.install_packages(['thermald'])

        subprocess.run(self.cmd_prefix + [
            'systemctl', 'enable', 'thermald'
        ])

    def install_vmware_workstation(self):
        """install VMware Workstation"""
        if not self.is_package_installed('vmware-workstation'):
            self.install_aur_packages(['vmware-workstation'])

        subprocess.run(self.cmd_prefix + [
            'systemctl', 'enable', 'vmware-networks'
        ])

        subprocess.run(self.cmd_prefix + [
            'systemctl', 'enable', 'vmware-usbarbitrator'
        ])

        subprocess.run(self.cmd_prefix + [
            '/usr/lib/vmware/bin/vmware-vmx-debug',
            '--new-sn', 'ZF3R0-FHED2-M80TY-8QYGC-NPKYF'
        ])

    def enable_gnome_appindicator(self):
        """enable GNOME AppIndicator"""
        if self.settings['desktop_environment'] != 'GNOME':
            return

        subprocess.run([
            'gnome-extensions',
            'enable',
            'appindicatorsupport@rgcjonas.gmail.com'
        ])

    def enable_gnome_vitals_extension(self):
        """enable GNOME vitals extension"""
        if self.settings['desktop_environment'] != 'GNOME':
            return

        subprocess.run([
            'gnome-extensions',
            'enable',
            'Vitals@CoreCoding.com'
        ])

    def configure_ufw(self):
        """configure ufw"""
        self.install_packages(['ufw', 'ufw-extras'])

        # only install gufw on GNOME
        if self.settings['desktop_environment'] == 'GNOME':
            if not self.is_package_installed('gufw'):
                self.install_packages(['gufw'])

        subprocess.run(self.cmd_prefix + [
            'systemctl', 'enable', 'ufw'
        ])

        subprocess.run(self.cmd_prefix + [
            'ufw', 'enable'
        ])

    def configure_emacs(self):
        """configure Emacs"""
        # make sure emacs installed
        if not self.is_package_installed('emacs'):
            self.install_packages(['emacs'])

        # install font use in Emacs config
        self.install_packages(['ttf-cascadia-code'])

        # configure for Vietnamese input in Emacs
        self.install_aur_packages(['xorg-fonts-misc-otb'])

        username = self.settings['username']
        cmd_prefix = (['arch-chroot', '-u', f'{username}', '/mnt']
                      if self.live_system
                      else [])
        custom_env = (dict(os.environ, HOME=f'/home/{username}')
                      if self.live_system
                      else None)

        # configure for user
        subprocess.run(cmd_prefix + [
            'git', 'clone', 'https://github.com/leanhtai01/emacsconfig',
            f'/home/{self.settings["username"]}/.config/emacs'
        ], env=custom_env)

        # configure for root
        subprocess.run(self.cmd_prefix + [
            'git', 'clone',
            'https://github.com/leanhtai01/emacsconfig',
            '/root/.config/emacs'
        ])

    def configure_gedit(self):
        """configure gedit"""
        if self.settings['desktop_environment'] != 'GNOME':
            return

        # make sure gedit and gedit-plugins is installed
        if not (self.is_package_installed('gedit') and
                self.is_package_installed('gedit-plugins')):
            self.install_packages(['gedit', 'gedit-plugins'])

        # display right margin
        self.gnome_gsettings_set(
            'org.gnome.gedit.preferences.editor',
            'display-right-margin',
            'true'
        )

        # insert spaces
        self.gnome_gsettings_set(
            'org.gnome.gedit.preferences.editor',
            'insert-spaces',
            'true'
        )

        # set tabs-size
        self.gnome_gsettings_set(
            'org.gnome.gedit.preferences.editor',
            'tabs-size',
            'uint32 4'
        )

        # set background pattern
        self.gnome_gsettings_set(
            'org.gnome.gedit.preferences.editor',
            'background-pattern',
            'grid'
        )

        # enable plugins
        self.gnome_gsettings_set(
            'org.gnome.gedit.plugins',
            'active-plugins',
            "['codecomment', 'colorpicker', 'wordcompletion', 'commander', \
                'bracketcompletion', 'smartspaces', 'spell', 'devhelp', \
                    'sessionsaver', 'git', 'terminal', 'sort', 'filebrowser', \
                        'modelines', 'docinfo', 'quickhighlight', \
                            'multiedit', 'drawspaces', 'bookmarks', \
                                'quickopen', 'findinfiles', 'externaltools']"
        )

    def execute_method(self, method, *args):
        """execute another method then release resources if needed"""
        method(*args)
        if self.live_system:
            if os.path.ismount('/mnt/dev'):
                subprocess.run('umount /mnt/dev', shell=True)

            if os.path.ismount('/mnt/tmp'):
                subprocess.run('umount /mnt/tmp', shell=True)

    def install_fcitx5_bamboo(self):
        """install fcitx5-bamboo"""
        self.install_packages(['fcitx5-bamboo'])

        # install input method module
        self.install_packages(['fcitx5-qt', 'fcitx5-gtk'])

        # install configuration tool
        self.install_packages(['fcitx5-configtool'])

        # set environment variables
        username = self.settings['username']
        cmd_prefix = (f'arch-chroot -u {username} /mnt '
                      if self.live_system
                      else '')

        subprocess.run(
            self.working_dir +
            f'/bash/configure_fcitx5.sh "{username}" "{cmd_prefix}"',
            shell=True
        )

    def install_ibus_bamboo(self):
        """install ibus-bamboo"""
        if not self.is_package_installed('ibus-bamboo'):
            self.install_aur_packages(['ibus-bamboo'])

    def install_input_method(self):
        """install input method based on desktop environment"""
        de = self.settings['desktop_environment']

        if de == 'GNOME':
            self.install_ibus_bamboo()
        elif de == 'Plasma':
            self.install_fcitx5_bamboo()

    def configure_input_method(self):
        """configure input method based on desktop environment"""
        de = self.settings['desktop_environment']

        if de == 'GNOME':
            self.configure_ibus_bamboo()

    def install_snapd(self):
        """install snapd"""
        if not self.is_package_installed('snapd'):
            self.install_aur_packages(['snapd'])

        self.systemctl_enable('apparmor.service')
        self.systemctl_enable('snapd.apparmor.service')
        self.systemctl_enable('snapd.socket')

    def install_tmcbeans_from_snap(self):
        """install TMCBeans from Snap"""
        if self.live_system:
            print('Must be install outside live system!')
        elif not self.is_package_installed('snapd'):
            print('snapd must be install first!')
        else:
            subprocess.run(
                'sudo systemctl restart snapd.seeded.service', shell=True
            )

            # updating snap
            subprocess.run(
                'sudo snap refresh', shell=True
            )

            # must be use jdk11 for TMCBeans to run
            self.install_packages(['jdk11-openjdk'])
            subprocess.run(
                'sudo archlinux-java set java-11-openjdk', shell=True
            )

            # allow the installation of classic snaps
            subprocess.run(
                'sudo ln -s /var/lib/snapd/snap /snap', shell=True
            )

            subprocess.run(
                'sudo snap install --classic tmcbeans', shell=True
            )

    def install_base_system(self):
        """install base system"""
        self.execute_method(self.disable_auto_generate_mirrorlist)
        self.execute_method(self.update_system_clock)
        self.execute_method(self.setup_mirrors)
        self.execute_method(self.prepare_disk)
        self.execute_method(self.install_essential_packages)
        self.execute_method(self.configure_fstab)
        self.execute_method(self.configure_time_zone)
        self.execute_method(self.configure_localization)
        self.execute_method(self.enable_multilib)
        self.execute_method(self.configure_network)
        self.execute_method(self.set_root_password)
        self.execute_method(self.add_normal_user)
        self.execute_method(
            self.allow_user_in_wheel_group_execute_any_command
        )
        self.execute_method(self.disable_sudo_password_prompt_timeout)
        self.execute_method(self.increase_sudo_timestamp_timeout)

        if self.partition_layout == 'encrypted':
            self.execute_method(
                self.configure_mkinitcpio_for_encrypted_system
            )

        self.execute_method(self.configure_mkinitcpio_for_hibernation)
        self.execute_method(self.configure_systemd_bootloader)
