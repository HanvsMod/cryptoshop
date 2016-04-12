#!/usr/bin/env python3
# -*-coding:Utf-8 -*

# py-cryptoshop Strong file encryption.
# Copyright(C) 2016 CORRAIRE Fabrice. antidote1911@gmail.com

# ############################################################################
# This file is part of Cryptoshop (full Qt5 gui for py-cryptoshop.
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

import os
import sys
import botan
import argon2
import getpass
import argparse
from tqdm import *

nonce_length = 16  # in bytes.(128 bits) Must be 16 for Serpent/CTR-BE
salt_size = 512  # in bits.(32 bytes)

argon2_timing_cost = 3000
argon2_memory_cost = 1024
argon2_parallelism = 2

chunk_size = 500000  # in bytes. (0.5 Mo)

# hmac_length must be 64 for hmac_algo= "HMAC(SHA-512)" or hmac_algo= "HMAC(Keccak-1600)"
# 32 for hmac_algo= "HMAC(SHA-256)"  for example.
hmac_algo = "HMAC(Keccak-1600)"
hmac_length = 64


def _calc_derivation2(passphrase, salt):
    """
    Calculate a 64 bit key derivation with Argon2, and split the output in two 32 bits key
    one for encryption and one for authentication.
    :param passphrase: A string of any length specified by user. This should be as long as varied as possible.
    :param salt: Randomly 256 bytes generated by Botan Random Number Generator.
    :return: Two 32 bits keys.    """

    argonhash = argon2.low_level.hash_secret_raw((str.encode(passphrase)), salt=salt, hash_len=64,
                                                 time_cost=argon2_timing_cost, memory_cost=argon2_memory_cost,
                                                 parallelism=argon2_parallelism, type=argon2.low_level.Type.I)
    key1 = argonhash[:32]
    key2 = argonhash[32:]
    return key1, key2


def _hmac_verify(hmac, mac):
    """
    The hmac comparison not use a naive "if hmac1==hmac" to prevent Timing Attack. We use constant time algorithm.
    https://en.wikipedia.org/wiki/Timing_attack

    :param hmac: bytes string with the first mac.
    :param mac: bytes string with the second mac.
    :return: True or False with always same time calculation.
    """
    if len(hmac) != len(mac):
        return
    result = 0
    for x, y in zip(hmac, mac):
        result |= x ^ y
    return result == 0


def _encry_decry_chunk(chunk, key, algo, bool_encry):
    """
    When bool_encry is True, encrypt a chunk of the file with the key and a randomly generated nonce. When it is False,
    the function extract the nonce from the cipherchunk (first 16 bits), and decrypt the rest of the chunk.

    :param chunk: a chunk in bytes to encrypt or decrypt.
    :param key: a 32 bits key in bytes.
    :param bool_encry: if bool_encry is True, chunk is encrypted. Else, it will be decrypted.
    :return: if bool_encry is True, corresponding nonce + cipherchunk else, a decrypted chunk.
    """
    engine = botan.cipher(algo=algo, encrypt=bool_encry)
    engine.set_key(key=key)
    if bool_encry is True:
        nonce = botan.rng().get(nonce_length)
        engine.start(nonce=nonce)
        return nonce + engine.finish(chunk)
    else:
        nonce = chunk[:nonce_length]
        cipherchunk = chunk[nonce_length:]
        engine.start(nonce=nonce)
        return engine.finish(cipherchunk)


def encryptfile(filename, passphrase, algo):
    """
    Encrypt a file and write it with .cryptoshop extension.

    :param filename: A string with the path to the file to encrypt.
    :param passphrase: A string with the user passphrase.
    :param algo: A string with the algorithm. Can be srp, aes, twf.
    :return: a dictionary with the results.
    """
    try:
        if algo == "srp":
            header = b"Cryptoshop srp 1.0"
            crypto_algo = "Serpent/CTR-BE"
        if algo == "aes":
            header = b"Cryptoshop aes 1.0"
            crypto_algo = "AES-256/CTR-BE"
        if algo == "twf":
            header = b"Cryptoshop twf 1.0"
            crypto_algo = "Twofish/CTR-BE"
        if algo != "srp" and algo != "aes" and algo != "twf":
            return "No valid algo. Use 'srp' 'aes' or 'twf'"
        outname = filename + ".cryptoshop"
        internal_key = botan.rng().get(64)  # The internal key for encryption...

        master_pass_salt = botan.rng().get(salt_size)

        # Passphrase derivation...
        masterkey = _calc_derivation2(passphrase=passphrase, salt=master_pass_salt[:(salt_size // 2)])
        encrypted_internal_key = _encry_decry_chunk(chunk=internal_key, key=masterkey[0], algo=crypto_algo,
                                                    bool_encry=True)
        # Hmac encrypted_internal_key...
        hmac_salt = master_pass_salt[(salt_size // 2):]
        hmac = botan.message_authentication_code(algo=hmac_algo)
        hmac.set_key(masterkey[1])
        hmac.update(header)
        hmac.update(hmac_salt)
        hmac.update(encrypted_internal_key)
        master_hmac = hmac.final()

        # Instantiate the internal hmac...
        hmac_internal_salt = botan.rng().get(salt_size)
        hmac_internal = botan.message_authentication_code(algo=hmac_algo)
        hmac_internal.set_key(internal_key[:32])
        hmac_internal.update(header)
        hmac_internal.update(hmac_internal_salt)

        with open(filename, 'rb') as filestream:
            with open(str(outname), 'wb') as filestreamout:
                file_size = os.stat(filename).st_size
                finished = False
                # the maximum of the progress bar is the total chunk to process. It's files_size // chunk_size
                bar = tqdm(range(file_size // chunk_size))
                while not finished:
                    chunk = filestream.read(chunk_size)
                    if len(chunk) == 0 or len(chunk) % chunk_size != 0:
                        finished = True
                    # encrypt a chunk and return an encryptedchunk (concatenation of an unique nonce + encryptedchunk)
                    encryptedchunk = _encry_decry_chunk(chunk=chunk, key=internal_key[32:], algo=crypto_algo,
                                                        bool_encry=True)
                    hmac_internal.update(encryptedchunk)
                    filestreamout.write(encryptedchunk)
                    bar.update(1)

            with open(str(outname), 'rb') as file:
                # Because hmac internal is computed at and of encryption, we can't write directly at top of file. But...
                # for write hmac code at the beginning, we need to write it in a different file, and append the content
                # of the encrypted file. Finally, we rename the tmp file with final name, and delete the encrypted file.
                # The final file structure is:
                # [header, salt1, hmac1, encrypted_key, hmac2, salt2, encryptedchunk1, encryptedchunk2.....]
                with open(str(".crypto_tmp"), 'wb') as tmpstream:
                    tmpstream.write(header)  # 18
                    tmpstream.write(master_pass_salt)  # 512
                    tmpstream.write(master_hmac)  # 64
                    tmpstream.write(encrypted_internal_key)  # (80) nonce_size + encryptedkeysize
                    tmpstream.write(hmac_internal.final())
                    tmpstream.write(hmac_internal_salt)
                    while True:
                        chunk = file.read(chunk_size*100)
                        tmpstream.write(chunk)
                        if len(chunk) == 0:
                            break

            os.remove(outname)
            os.rename(".crypto_tmp", outname)
            outname_size = os.stat(outname).st_size

            result = {"success": "successfully encrypted", "original_file": filename, "original_file_size": file_size,
                      "output_file": outname, "output_file_size": outname_size,
                      "chunks_encrypted": file_size // chunk_size, "chunks_size": chunk_size, "algorithm": crypto_algo}
            return result

    except IOError:
        exit("Error: file \"" + filename + "\" was not found.")


def decryptfile(filename, passphrase):
    """
    Decrypt a file and write corresponding decrypted file. We remove the .cryptoshop extension.

    :param filename: A string with the path to the file to decrypt.
    :param passphrase: A string with the user passphrase.
    :return: a dictionary with the results.
    """
    try:
        outname = os.path.splitext(filename)[0].split("_")[-1]  # create a string file name without extension.
        with open(filename, 'rb') as filestream:

            with open(str(outname), 'wb') as filestreamout:
                fileheader = filestream.read(18)

                if fileheader == b"Cryptoshop srp 1.0":
                    decrypt_algo = "Serpent/CTR-BE"
                if fileheader == b"Cryptoshop aes 1.0":
                    decrypt_algo = "AES-256/CTR-BE"
                if fileheader == b"Cryptoshop twf 1.0":
                    decrypt_algo = "Twofish/CTR-BE"
                if fileheader != b"Cryptoshop srp 1.0" and fileheader != b"Cryptoshop aes 1.0" and fileheader != b"Cryptoshop twf 1.0":
                    os.remove(outname)
                    return {"success": "Error: Bad header"}

                master_pass_salt = filestream.read(salt_size)
                master_hmac = filestream.read(hmac_length)
                encrypted_internal_key = filestream.read(nonce_length + 64)  # nonce length + encryptedkey length

                # Derive the passphrase...
                masterkey = _calc_derivation2(passphrase=passphrase, salt=master_pass_salt[:salt_size // 2])

                # hmac encrypted_internal_key verification. If good, the internal key is decrypted...
                hmac_salt = master_pass_salt[salt_size // 2:]
                hmac = botan.message_authentication_code(algo=hmac_algo)
                hmac.set_key(masterkey[1])
                hmac.update(fileheader)
                hmac.update(hmac_salt)
                hmac.update(encrypted_internal_key)

                calculated_master_hmac = hmac.final()
                verify = _hmac_verify(calculated_master_hmac, master_hmac)
                if verify is False:
                    os.remove(outname)
                    return {"success": "Bad password or corrupt / modified data."}

                # decrypt internal key...
                decrypted_internal_key = _encry_decry_chunk(chunk=encrypted_internal_key, key=masterkey[0],
                                                            algo=decrypt_algo,
                                                            bool_encry=False)
                filehmac = filestream.read(hmac_length)
                salt = filestream.read(salt_size)

                # Instantiate the internal hmac
                hmac_internal = botan.message_authentication_code(algo=hmac_algo)
                hmac_internal.set_key(decrypted_internal_key[:32])
                hmac_internal.update(fileheader)
                hmac_internal.update(salt)

                files_size = os.stat(filename).st_size

                # the maximum of the progress bar is the total chunk to process. It's files_size // chunk_size
                bar = tqdm(range(files_size // chunk_size))
                while True:
                    # Don't forget... an encrypted chunk is nonce and cipher chunk concatenation
                    chunk = filestream.read(chunk_size + nonce_length)
                    hmac_internal.update(chunk)
                    if len(chunk) == 0:
                        break
                        # Chunk decryption.
                    original_chunk = _encry_decry_chunk(chunk=chunk, key=decrypted_internal_key[32:], algo=decrypt_algo,
                                                        bool_encry=False)
                    filestreamout.write(original_chunk)
                    bar.update(1)
                hmacfinal = hmac_internal.final()

                # hmac internal verification
                verify = _hmac_verify(hmacfinal, filehmac)
                if verify is False:
                    os.remove(outname)
                    return {"success": "Bad password or corrupt / modified data."}

        outname_size = os.stat(outname).st_size

        result = {"success": "successfully decrypted", "encrypted_file": filename, "encrypted_file_size": files_size,
                  "decrypted_file": outname, "output_file_size": outname_size,
                  "chunks_decrypted": files_size // chunk_size, "chunks_size": chunk_size, "algorithm": decrypt_algo}
        return result

    except IOError:
        exit("Error: file \"" + filename + "\" was not found.")


# ./stream.py -e test -a aes         if no algo specified, Serpent (srp) is default.
# ./stream.py -d test.cryptoshop     no need to specify algo. It is detected by decryption routine.

def main():
    # parse command line arguments...
    parser = argparse.ArgumentParser(description="Encrypt or decrypt a file using Serpent-256, AES-256 or Twofish-256")
    parser.add_argument("filename", type=str,
                        help="file to encrypt or decrypt")
    parser.add_argument("-a", "--algo", type=str,
                        default="srp",
                        help="specify algo. Can be srp, aes or twf. Default is srp. Not used for decrypt.")

    # encrypt OR decrypt...
    grouped = parser.add_mutually_exclusive_group(required=True)
    grouped.add_argument("-e", "--encrypt",
                         help="encrypt file", action="store_true")
    grouped.add_argument("-d", "--decrypt",
                         help="decrypt file", action="store_true")
    args = parser.parse_args()
    filename = args.filename

    if args.encrypt:
        algo = args.algo

        passw = str(getpass.getpass("Password:"))
        passw_conf = str(getpass.getpass("Confirm password:"))

        # check if second pass is the same as first entry pass...
        if passw != passw_conf:
            exit("Error: passwords you provided do not match")
        result = encryptfile(filename=filename, passphrase=passw, algo=algo)
        print(result["success"])

    elif args.decrypt:
        passw = str(getpass.getpass("Password:"))
        result = decryptfile(filename=filename, passphrase=passw)
        print(result["success"])


if __name__ == '__main__':
    sys.exit(main() or 0)
