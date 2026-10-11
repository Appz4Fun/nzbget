// Verbatim fold from c2316ef5e5ac7d5fb1c309e52de9e40dbc76c63e ParChecker.cpp
	// compute file CRC using CRCs of blocks
	uint32 parCrc = 0;
	for (uint32 i = 0; i < packet->BlockCount(); i++)
	{
		const Par2::FILEVERIFICATIONENTRY* entry = packet->VerificationEntry(i);
		Par2::u32 blockCrc = entry->crc;
		parCrc = i == 0 ? blockCrc : Crc32::Combine(parCrc, blockCrc, (uint32)blocksize);
	}
	return parCrc;
