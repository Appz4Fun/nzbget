// Verbatim full body from c2316ef5e5ac7d5fb1c309e52de9e40dbc76c63e

	Par2::u64 blocksize = GetRepairer()->mainpacket->BlockSize();
	Par2::VerificationPacket* packet = sourceFile.GetVerificationPacket();

	// extend lDownloadCrc to block size
	downloadCrc = Par2::CRCUpdateBlock(downloadCrc ^ 0xFFFFFFFF,
		(blocksize * packet->BlockCount() > sourceFile.GetTargetFile()->FileSize() ?
			blocksize * packet->BlockCount() - sourceFile.GetTargetFile()->FileSize() : 0)
		) ^ 0xFFFFFFFF;
	debug("Download-CRC: %.8x", downloadCrc);

	// compute file CRC using CRCs of blocks
	uint32 parCrc = 0;
	for (uint32 i = 0; i < packet->BlockCount(); i++)
	{
		const Par2::FILEVERIFICATIONENTRY* entry = packet->VerificationEntry(i);
		Par2::u32 blockCrc = entry->crc;
		parCrc = i == 0 ? blockCrc : Crc32::Combine(parCrc, blockCrc, (uint32)blocksize);
	}
	std::string fileName = sourceFile.GetTargetFile()->FileName();
	debug("Block-CRC: %x, filename: %s", parCrc, FileSystem::BaseFileName(fileName.c_str()));

	return parCrc == downloadCrc;
