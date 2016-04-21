#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Cryptoshop Strong file encryption.
# Encrypt and decrypt file in GCM mode with AES, Serpent or Twofish as secure as possible.
# Copyright(C) 2016 CORRAIRE Fabrice. antidote1911@gmail.com

# ############################################################################
# This file is part of Cryptoshop-GUI (full Qt5 gui for Cryptoshop).
#
#    Cryptoshop is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    Cryptoshop is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with Cryptoshop.  If not, see <http://www.gnu.org/licenses/>.
# ############################################################################

"""
    Cryptoshop implementation.
    Encrypt and decrypt file in GCM mode with AES, Serpent or Twofish as secure as possible.

    Usage:
    from cryptoshop import encryptfile
    from cryptoshop import decryptfile

    result1 = encryptfile(filename="test", passphrase="mypassword", algo="srp")
    print(result1)

    result2 = decryptfile(filename="test.cryptoshop", passphrase="mypassword")
    print(result2)

"""

import os
import sys
from tqdm import *

from ._cascade_engine import encry_decry_cascade
from ._derivation_engine import calc_derivation
from ._chunk_engine import encry_decry_chunk
from ._nonce_engine import nonce_length
from ._settings import __version__, __chunk_size__, __gcmtag_length__

try:
    import botan
except:
    print("Please install the last version of Botan crypto library.")
    print("http://botan.randombit.net/#download")
    print("For Linux users, try to find it in your package manager.")
    sys.exit(0)

b_version = bytes(__version__.encode('utf-8'))
salt_size = 512  # in bits.(64 bytes)

# ------------------------------------------------------------------------------
# Constant variables
# ------------------------------------------------------------------------------
internal_key_length = 32  # in bytes (256 bits).
encrypted_key_length = 143  # in bytes (1144 bits):   3*nonce + 3*tag + 32
header_length = 20  # in bits (2.5 bytes)


# ------------------------------------------------------------------------------
# String Cascade Encryption / Decryption
# ------------------------------------------------------------------------------

def encryptstring(string, passphrase):
    header = b"Cryptoshop str " + b_version
    salt = botan.rng().get(salt_size)

    key = calc_derivation(passphrase=passphrase, salt=salt)
    out = encry_decry_cascade(data=string, masterkey=key, bool_encry=True, assoc_data=header)
    return header + salt + out


def decryptstring(string, passphrase):
    header = string[:header_length]
    salt = string[header_length:salt_size + header_length]
    encryptedstring = string[header_length + salt_size:]

    key = calc_derivation(passphrase=passphrase, salt=salt)
    out = encry_decry_cascade(data=encryptedstring, masterkey=key, bool_encry=False, assoc_data=header)
    return out.decode('utf-8')


# ------------------------------------------------------------------------------
# File Encryption / Decryption
# ------------------------------------------------------------------------------

def encryptfile(filename, passphrase, algo='srp'):
    """
    Encrypt a file and write it with .cryptoshop extension.
    :param filename: a string with the path to the file to encrypt.
    :param passphrase: a string with the user passphrase.
    :param algo: a string with the algorithm. Can be srp, aes, twf. Default is srp.
    :return: a string with "successfully encrypted" or error.
    """
    try:
        if algo == "srp":
            header = b"Cryptoshop srp " + b_version
            crypto_algo = "Serpent/GCM"
        if algo == "aes":
            header = b"Cryptoshop aes " + b_version
            crypto_algo = "AES-256/GCM"
        if algo == "twf":
            header = b"Cryptoshop twf " + b_version
            crypto_algo = "Twofish/GCM"
        if algo != "srp" and algo != "aes" and algo != "twf":
            return "No valid algo. Use 'srp' 'aes' or 'twf'"
        outname = filename + ".cryptoshop"

        internal_key = botan.rng().get(internal_key_length)

        # Passphrase derivation...
        salt = botan.rng().get(salt_size)
        masterkey = calc_derivation(passphrase=passphrase, salt=salt)

        # Encrypt internal key...
        encrypted_key = encry_decry_cascade(data=internal_key, masterkey=masterkey,
                                            bool_encry=True,
                                            assoc_data=header + salt)
        with open(filename, 'rb') as filestream:
            with open(str(outname), 'wb') as filestreamout:
                filestreamout.write(header)
                filestreamout.write(salt)
                filestreamout.write(encrypted_key)
                file_size = os.stat(filename).st_size
                finished = False
                # the maximum of the progress bar is the total chunk to process. It's files_size // chunk_size
                bar = tqdm(range(file_size // __chunk_size__))
                while not finished:
                    chunk = filestream.read(__chunk_size__)
                    if len(chunk) == 0 or len(chunk) % __chunk_size__ != 0:
                        finished = True
                    # An encrypted-chunk output is nonce, gcmtag, and cipher-chunk concatenation.
                    encryptedchunk = encry_decry_chunk(chunk=chunk, key=internal_key, bool_encry=True,
                                                       algo=crypto_algo, assoc_data=header + salt + encrypted_key)
                    filestreamout.write(encryptedchunk)
                    bar.update(1)

            return "successfully encrypted"

    except IOError:
        exit("Error: file \"" + filename + "\" was not found.")


def decryptfile(filename, passphrase):
    """
    Decrypt a file and write corresponding decrypted file. We remove the .cryptoshop extension.
    :param filename: a string with the path to the file to decrypt.
    :param passphrase: a string with the user passphrase.
    :return: a string with "successfully decrypted" or error.
    """
    try:
        outname = os.path.splitext(filename)[0].split("_")[-1]  # create a string file name without extension.
        with open(filename, 'rb') as filestream:
            fileheader = filestream.read(header_length)

            if fileheader == b"Cryptoshop srp " + b_version:
                decrypt_algo = "Serpent/GCM"
            if fileheader == b"Cryptoshop aes " + b_version:
                decrypt_algo = "AES-256/GCM"
            if fileheader == b"Cryptoshop twf " + b_version:
                decrypt_algo = "Twofish/GCM"
            if fileheader != b"Cryptoshop srp " + b_version and fileheader != b"Cryptoshop aes " + b_version and fileheader != b"Cryptoshop twf " + b_version:
                return "Error: Bad header"

            salt = filestream.read(salt_size)
            encrypted_key = filestream.read(encrypted_key_length)

            # Derive the passphrase...
            masterkey = calc_derivation(passphrase=passphrase, salt=salt)

            # Decrypt internal key...
            try:
                internal_key = encry_decry_cascade(data=encrypted_key, masterkey=masterkey,
                                                   bool_encry=False, assoc_data=fileheader + salt)
            except Exception as e:
                return e

            with open(str(outname), 'wb') as filestreamout:
                files_size = os.stat(filename).st_size

                # the maximum of the progress bar is the total chunk to process. It's files_size // chunk_size
                bar = tqdm(range(files_size // __chunk_size__))
                while True:
                    # Don't forget... an encrypted chunk is nonce, gcmtag, and cipher-chunk concatenation.
                    encryptedchunk = filestream.read(nonce_length + __gcmtag_length__ + __chunk_size__)
                    if len(encryptedchunk) == 0:
                        break

                    # Chunk decryption.
                    try:
                        original = encry_decry_chunk(chunk=encryptedchunk, key=internal_key, algo=decrypt_algo,
                                                     bool_encry=False, assoc_data=fileheader + salt + encrypted_key)
                    except Exception as e:
                        return e
                    else:
                        filestreamout.write(original)
                        bar.update(1)

        return "successfully decrypted"

    except IOError:
        exit("Error: file \"" + filename + "\" was not found.")
