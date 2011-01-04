class Tables(object):

    def __init__(self):
        self._gsub = Table()
        self._gsub.tag = "GSUB"
        self._gpos = Table()
        self._gpos.tag = "GPOS"

    def __getitem__(self, key):
        if key == "GSUB":
            return self._gsub
        if key == "GPOS":
            return self._gpos
        raise KeyError, "Unknonw table %s." % key

    def _load(self, font):
        if font.has_key("GSUB"):
            self._gsub._load(font["GSUB"].table, "GSUB")


class Table(list):

    def __init__(self):
        self.tag = None
        self.classes = Classes()
        self.lookups = []

    # writing

    def write(self, writer):
        # language systems
        languageSystems = set()
        for feature in self:
            for script in feature.scripts:
                scriptTag = script.tag
                if scriptTag == "DFLT":
                    scriptTag = None
                for language in script.languages:
                    languageTag = language.tag
                    languageSystems.add((scriptTag, languageTag))
        for scriptTag, languageTag in sorted(languageSystems):
            if scriptTag is None:
                scriptTag = "DFLT"
            writer.addLanguageSystem(scriptTag, languageTag)
        # classes
        for name, members in sorted(self.classes.items()):
            writer.addClassDefinition(name, members)
        # lookups
        for lookup in self.lookups:
            lookupWriter = writer.addLookup(lookup.name)
            lookup.write(lookupWriter)
        # features
        for feature in self:
            featureWriter = writer.addFeature(feature.tag)
            feature.write(featureWriter)

    # manipulation

    def removeGlyphs(self, glyphNames):
        self.classes.removeGlyphs(glyphNames)
        for lookup in self.lookups:
            lookup.removeGlyphs(glyphNames)
        for feature in self:
            feature.removeGlyphs(glyphNames)

    def renameGlyphs(self, glyphMapping):
        self.classes.renameGlyphs(glyphMapping)
        for lookup in self.lookups:
            lookup.renameGlyphs(glyphMapping)
        for feature in self:
            feature.renameGlyphs(glyphMapping)

    def cleanup(self):
        pass

    # loading

    def _load(self, table, tableTag):
        # first pass through the features
        features = {}
        for scriptRecord in table.ScriptList.ScriptRecord:
            scriptTag = scriptRecord.ScriptTag
            if scriptTag == "DFLT":
                scriptTag = None
            # default
            languageTag = None
            featureIndexes = scriptRecord.Script.DefaultLangSys.FeatureIndex
            for index in featureIndexes:
                featureRecord = table.FeatureList.FeatureRecord[index]
                featureTag = featureRecord.FeatureTag
                lookupIndexes = featureRecord.Feature.LookupListIndex
                if featureTag not in features:
                    features[featureTag] = []
                features[featureTag].append((scriptTag, languageTag, lookupIndexes))
            # language specific
            for languageRecord in scriptRecord.Script.LangSysRecord:
                languageTag = languageRecord.LangSysTag
                featureIndexes = languageRecord.LangSys.FeatureIndex
                for index in featureIndexes:
                    featureRecord = table.FeatureList.FeatureRecord[index]
                    featureTag = featureRecord.FeatureTag
                    lookupIndexes = featureRecord.Feature.LookupListIndex
                    if featureTag not in features:
                        features[featureTag] = []
                    features[featureTag].append((scriptTag, languageTag, lookupIndexes))
        # order the features
        sorter = []
        for featureTag, records in features.items():
            indexes = []
            for (scriptTag, languageTag, lookupIndexes) in records:
                indexes += lookupIndexes
            indexes = tuple(sorted(set(indexes)))
            sorter.append((indexes, featureTag))
        featureOrder = [featureTag for (indexes, featureTag) in sorted(sorter)]
        # sort the script and language records
        # grab the lookup records
        for featureTag, records in features.items():
            _records = []
            for (scriptTag, languageTag, lookupIndexes) in sorted(records):
                if scriptTag is None:
                    scriptTag = "DFLT"
                lookupRecords = [table.LookupList.Lookup[index] for index in lookupIndexes]
                _records.append((scriptTag, languageTag, lookupRecords))
            features[featureTag] = _records
        # do the official packing
        for featureTag in featureOrder:
            records = features[featureTag]
            feature = Feature()
            feature.tag = featureTag
            feature._load(table, tableTag, records)
            self.append(feature)
        # compress
        self._compress()

    # compression

    def _compress(self):
        self._compressLookups()
        self._compressClasses()

    def _compressLookups(self):
        """
        Locate lookups that occur in more than one feature.
        These can be promoted to global lookups.
        """
        # find all potential lookups
        lookupOrder = []
        candidates = {}
        for feature in self:
            lookups = feature._findLookups()
            for lookup in lookups:
                if lookup not in lookupOrder:
                    lookupOrder.append(lookup)
                if lookup not in candidates:
                    candidates[lookup] = set()
                candidates[lookup].add(feature.tag)
        # store all lookups that occur in > 1 features
        usedNames = set()
        lookups = {}
        for lookup in lookupOrder:
            features = candidates[lookup]
            if len(features) == 1:
                continue
            lookupName = nameLookup(features)
            counter = 1
            while 1:
                name = lookupName + "_" + str(counter)
                counter += 1
                if name not in usedNames:
                    lookupName = name
                    usedNames.add(lookupName)
                    break
            lookups[lookupName] = lookup
        for name, lookup in sorted(lookups.items()):
            self.lookups.append(lookup)
        # populate global lookups
        flippedLookups = {}
        for k, v in lookups.items():
            flippedLookups[v] = k
        for feature in self:
            feature._populateGlobalLookups(flippedLookups)
        # name the global lookups
        # this can't be done earlier because it
        # will throw off the == comparison when
        # trying to find duplicate lookups
        for name, lookup in lookups.items():
            lookup.name = name
        # compress feature level lookups
        for feature in self:
            feature._compressLookups()

    def _compressClasses(self):
        # find all potential classes
        classOrder = []
        potentialClasses = {}
        for feature in self:
            candidates = feature._findPotentialClasses()
            for candidate in candidates:
                if candidate not in potentialClasses:
                    potentialClasses[candidate] = []
                    classOrder.append(candidate)
                potentialClasses[candidate].append(feature.tag)
        # name the classes
        usedNames = set()
        classes = {}
        featureClasses = {}
        for members in classOrder:
            features = potentialClasses[members]
            className = nameClass(features, members)
            counter = 1
            while 1:
                name = className + "_" + str(counter)
                counter += 1
                if name not in usedNames:
                    className = name
                    usedNames.add(className)
                    break
            classes[members] = className
            if len(features) > 1:
                self.classes[className] = Class(members)
            else:
                feature = features[0]
                if feature not in featureClasses:
                    featureClasses[feature] = {}
                featureClasses[feature][className] = members
        # populate the classes
        for feature in self:
            feature._populateClasses(classes, featureClasses.get(feature.tag, {}))


class Feature(object):

    def __init__(self):
        self.tag = None
        self.classes = Classes()
        self.scripts = []

    # writing

    def write(self, writer):
        # classes
        for name, members in sorted(self.classes.items()):
            writer.addClassDefinition(name, members)
        # scripts
        for script in self.scripts:
            script.write(writer)

    # loading

    def _load(self, table, tableTag, records):
        for (scriptTag, languageTag, lookupRecords) in records:
            if self.scripts and self.scripts[-1].tag == scriptTag:
                script = self.scripts[-1]
            else:
                script = Script()
                script.tag = scriptTag
                self.scripts.append(script)
            script._load(table, tableTag, languageTag, lookupRecords)

    # manipulation

    def removeGlyphs(self, glyphNames):
        self.classes.removeGlyphs(glyphNames)
        for script in self.scripts:
            script.removeGlyphs(glyphNames)

    def renameGlyphs(self, glyphMapping):
        self.classes.renameGlyphs(glyphMapping)
        for script in self.scripts:
            script.renameGlyphs(glyphMapping)

    def cleanup(self):
        pass

    # compress lookups

    def _findLookups(self):
        lookups = []
        for script in self.scripts:
            for lookup in script._findLookups():
                if lookup not in lookups:
                    lookups.append(lookup)
        return lookups

    def _populateGlobalLookups(self, flippedLookups):
        for script in self.scripts:
            script._populateGlobalLookups(flippedLookups)

    def _compressLookups(self):
        self._compressFeatureLookups()
        self._compressDefaultLookups()

    def _compressFeatureLookups(self):
        # find
        lookups = {}
        counter = 1
        for lookup in self._findLookups():
            lookupName = nameLookup([self.tag]) + "_" + str(counter)
            lookups[lookup] = lookupName
            counter += 1
        # populate
        haveSeen = dict.fromkeys(lookups.values(), False)
        for script in self.scripts:
            script._populateFeatureLookups(lookups, haveSeen)
        # name
        for lookup, name in lookups.items():
            lookup.name = name

    def _compressDefaultLookups(self):
        # group the lookups based on script and language
        defaultLookups = []
        scriptDefaultLookups = {}
        languageSpecificLookups = {}
        for script in self.scripts:
            for language in script.languages:
                # check to make sure that the default hasn't happened twice
                if script.tag == "DFLT" and language.tag is None:
                    pass
                elif language.tag is None:
                    assert script.tag not in scriptDefaultLookups, "Default language appears more than once."
                    scriptDefaultLookups[script.tag] = (language, [])
                else:
                    assert (script.tag, language.tag) not in languageSpecificLookups, "Script+language combo appears more than once"
                    languageSpecificLookups[script.tag, language.tag] = (language, [])
                # store the lookups
                for lookup in language.lookups:
                    if script.tag == "DFLT" and language.tag is None:
                        defaultLookups.append(lookup)
                    elif language.tag is None:
                        scriptDefaultLookups[script.tag][1].append(lookup)
                    else:
                        languageSpecificLookups[script.tag, language.tag][1].append((lookup))
        # clear out redundant lookups from scripts
        for scriptTag, (language, lookups) in scriptDefaultLookups.items():
            # compare and slice as necessary
            newLookups = []
            for index, lookup in enumerate(lookups):
                if index >= len(defaultLookups) or lookup.name != defaultLookups[index].name:
                    newLookups += lookups[index:]
                    break
            language.lookups = newLookups
            scriptDefaultLookups[scriptTag] = (language, newLookups)
        # clear out redundant lookups from languages
        for (scriptTag, languageTag), (language, lookups) in languageSpecificLookups.items():
            # create a default comparable
            defaultLookupNames = [lookup.name for lookup in defaultLookups]
            scriptData = scriptDefaultLookups.get(scriptTag)
            if scriptData:
                script, scriptLookups = scriptData
                defaultLookupNames += [lookup.name for lookup in scriptLookups]
            # create a comparable for this language
            languageLookupNames = [lookup.name for lookup in lookups]
            # compare
            includeDefault = True
            if len(defaultLookupNames) > len(languageLookupNames):
                includeDefault = False
            else:
                languageSlice = languageLookupNames[:len(defaultLookupNames)]
                if languageSlice != defaultLookupNames:
                    includeDefault = False
            # adjust
            if not includeDefault:
                language.includeDefault = False
            else:
                language.lookups = language.lookups[len(defaultLookupNames):]

    # compress classes

    def _findPotentialClasses(self):
        candidates = []
        for script in self.scripts:
            for candidate in script._findPotentialClasses():
                if candidate not in candidates:
                    candidates.append(candidate)
        return candidates

    def _populateClasses(self, allClasses, featureClasses):
        new = {}
        for name, members in featureClasses.items():
            new[name] = Class(members)
        self.classes.update(new)
        for script in self.scripts:
            script._populateClasses(allClasses)


class Script(object):

    def __init__(self):
        self.tag = None
        self.languages = []

    # writing

    def write(self, writer):
        writer.addScript(self.tag)
        # languages
        for language in self.languages:
            language.write(writer)

    # loading

    def _load(self, table, tableTag, languageTag, lookupRecords):
        language = Language()
        language.tag = languageTag
        language._load(table, tableTag, lookupRecords)
        self.languages.append(language)

    # manipulation

    def removeGlyphs(self, glyphNames):
        for language in self.languages:
            language.removeGlyphs(glyphNames)

    def renameGlyphs(self, glyphMapping):
        for language in self.languages:
            language.renameGlyphs(glyphMapping)

    def cleanup(self):
        pass

    # compression

    def _findLookups(self):
        lookups = []
        for language in self.languages:
            for lookup in language.lookups:
                if isinstance(lookup, LookupReference):
                    continue
                if lookup not in lookups:
                    lookups.append(lookup)
        return lookups

    def _populateGlobalLookups(self, flippedLookups):
        for language in self.languages:
            language._populateGlobalLookups(flippedLookups)

    def _populateFeatureLookups(self, flippedLookups, haveSeen):
        for language in self.languages:
            language._populateFeatureLookups(flippedLookups, haveSeen)

    def _findPotentialClasses(self):
        candidates = []
        for language in self.languages:
            for candidate in language._findPotentialClasses():
                if candidate not in candidates:
                    candidates.append(candidate)
        return candidates

    def _populateClasses(self, classes):
        for language in self.languages:
            language._populateClasses(classes)


class Language(object):

    def __init__(self):
        self.tag = None
        self.includeDefault = True
        self.lookups = []

    # writing

    def write(self, writer):
        writer.addLanguage(self.tag, includeDefault=self.includeDefault)
        # lookups
        for lookup in self.lookups:
            if isinstance(lookup, LookupReference):
                writer.addLookupReference(lookup.name)
            else:
                lookupWriter = writer.addLookup(lookup.name)
                lookup.write(lookupWriter)

    # loading

    def _load(self, table, tableTag, lookupRecords):
        for lookupRecord in lookupRecords:
            lookup = Lookup()
            lookup._load(table, tableTag, lookupRecord)
            self.lookups.append(lookup)

    # manipulation

    def removeGlyphs(self, glyphNames):
        for lookup in self.lookups:
            lookup.removeGlyphs(glyphNames)

    def renameGlyphs(self, glyphMapping):
        for lookup in self.lookups:
            lookup.renameGlyphs(glyphMapping)

    def cleanup(self):
        pass

    # compress lookups

    def _populateGlobalLookups(self, flippedLookups):
        lookups = []
        for lookup in self.lookups:
            if lookup in flippedLookups:
                lookupName = flippedLookups[lookup]
                lookup = LookupReference()
                lookup.name = lookupName
            lookups.append(lookup)
        self.lookups = lookups

    def _populateFeatureLookups(self, flippedLookups, haveSeen):
        lookups = []
        for lookup in self.lookups:
            if isinstance(lookup, LookupReference):
                pass
            elif lookup in flippedLookups:
                lookupName = flippedLookups[lookup]
                if haveSeen[lookupName]:
                    lookup = LookupReference()
                    lookup.name = lookupName
                else:
                    haveSeen[lookupName] = True
            lookups.append(lookup)
        self.lookups = lookups

    # compress classes

    def _findPotentialClasses(self):
        candidates = []
        for lookup in self.lookups:
            if isinstance(lookup, LookupReference):
                continue
            for candidate in lookup._findPotentialClasses():
                if candidate not in candidates:
                    candidates.append(candidate)
        return candidates

    def _populateClasses(self, classes):
        for lookup in self.lookups:
            if isinstance(lookup, LookupReference):
                continue
            lookup._populateClasses(classes)


class Lookup(object):

    def __init__(self):
        self.name = None
        self.type = None
        self.flag = LookupFlag()
        self.subtables = []

    # writing

    def write(self, writer):
        # lookup flag
        self.flag.write(writer)
        # subtables
        for subtable in self.subtables:
            subtable.write(writer)

    # loading

    def _load(self, table, tableTag, lookupRecord):
        self.type = lookupRecord.LookupType
        self.flag._load(lookupRecord.LookupFlag)
        if tableTag == "GSUB":
            subtableClass = GSUBSubtable
        else:
            raise NotImplementedError
        for subtableRecord in lookupRecord.SubTable:
            subtable = subtableClass()
            subtable._load(table, tableTag, self.type, subtableRecord)
            self.subtables.append(subtable)

    # manipulation

    def removeGlyphs(self, glyphNames):
        for subtable in self.subtables:
            subtable.removeGlyphs(glyphNames)

    def renameGlyphs(self, glyphMapping):
        for subtable in self.subtables:
            subtable.renameGlyphs(glyphMapping)

    def cleanup(self):
        pass

    # compression

    def _findPotentialClasses(self):
        candidates = []
        for subtable in self.subtables:
            for candidate in subtable._findPotentialClasses():
                if candidate not in candidates:
                    candidates.append(candidate)
        return candidates

    def _populateClasses(self, classes):
        for subtable in self.subtables:
            subtable._populateClasses(classes)

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False
        if self.type != other.type:
            return False
        if self.flag != other.flag:
            return False
        if self.subtables != other.subtables:
            return False
        return True

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        s = "Lookup | name=%s type=%d flag=%s subtables=%s" % (
            self.name,
            self.type,
            str(hash(self.flag)),
            " ".join([str(hash(i)) for i in self.subtables])
        )
        return hash(s)


class LookupReference(object):

    def __init__(self):
        self.name = None

    def write(self, writer):
        writer.addLookupReference(self.name)

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False
        return self.name == other.name

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        s = "LookupReference | name=%s" % self.name
        return hash(s)


class LookupFlag(object):

    def __init__(self):
        self.rightToLeft = False
        self.ignoreBaseGlyphs = False
        self.ignoreLigatures = False
        self.ignoreMarks = False
        self.markAttachmentType = False

    def write(self, writer):
        writer.addLookupFlag(
            rightToLeft=self.rightToLeft,
            ignoreBaseGlyphs=self.ignoreBaseGlyphs,
            ignoreLigatures=self.ignoreLigatures,
            ignoreMarks=self.ignoreMarks,
            markAttachmentType=self.markAttachmentType
        )

    def _load(self, lookupFlag):
        self.rightToLeft = bool(lookupFlag & 0x0001)
        self.ignoreBaseGlyphs = bool(lookupFlag & 0x0002)
        self.ignoreLigatures = bool(lookupFlag & 0x0004)
        self.ignoreMarks = bool(lookupFlag & 0x0008)
        self.markAttachmentType = bool(lookupFlag & 0xFF00)

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False
        if self.rightToLeft != other.rightToLeft:
            return False
        if self.ignoreBaseGlyphs != other.ignoreBaseGlyphs:
            return False
        if self.ignoreLigatures != other.ignoreLigatures:
            return False
        if self.ignoreMarks != other.ignoreMarks:
            return False
        if self.markAttachmentType != other.markAttachmentType:
            return False
        return True

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        s = "LookupFlag | rightToLeft=%s ignoreBaseGlyphs=%s ignoreLigatures=%s ignoreMarks=%s markAttachmentType=%s" % (
            self.rightToLeft,
            self.ignoreBaseGlyphs,
            self.ignoreLigatures,
            self.ignoreMarks,
            self.markAttachmentType
        )
        return hash(s)


class GSUBSubtable(object):

    def __init__(self):
        self.type = None
        self._backtrack = []
        self._lookahead = []
        self._target = []
        self._substitution = []

    # attribute setting

    def _get_backtrack(self):
        return self._backtrack

    def _set_backtrack(self, value):
        self._backtrack = Sequence(value)

    backtrack = property(_get_backtrack, _set_backtrack)

    def _get_lookahead(self):
        return self._lookahead

    def _set_lookahead(self, value):
        self._lookahead = Sequence(value)

    lookahead = property(_get_lookahead, _set_lookahead)

    def _get_target(self):
        return self._target

    def _set_target(self, value):
        self._target = value

    target = property(_get_target, _set_target)

    def _get_substitution(self):
        return self._substitution

    def _set_substitution(self, value):
        self._substitution = value

    substitution = property(_get_substitution, _set_substitution)

    # type routing

    def _load(self, table, tableTag, type, subtable):
        self.type = type
        if type == 1:
            self._loadType1(subtable)
        elif type == 2:
            self._loadType2(subtable)
        elif type == 3:
            self._loadType3(subtable)
        elif type == 4:
            self._loadType4(subtable)
        elif type == 5:
            self._loadType5(subtable)
        elif type == 6:
            self._loadType6(table, tableTag, subtable)
        elif type == 7:
            self._loadType7(subtable)

    # write

    def write(self, writer):
        target = [self._flattenClassReferences(i) for i in self.target]
        substitution = [self._flattenClassReferences(i) for i in self.substitution]
        backtrack = self._flattenClassReferences(self.backtrack)
        lookahead = self._flattenClassReferences(self.lookahead)
        writer.addGSUBSubtable(target, substitution, self.type, backtrack=backtrack, lookahead=lookahead)

    def _flattenClassReferences(self, sequence):
        newSequence = []
        for group in sequence:
            newGroup = Class()
            for member in group:
                if isinstance(member, ClassReference):
                    member = member.name
                newGroup.append(member)
            newSequence.append(newGroup)
        return newSequence

    # type 1

    def _loadType1(self, subtable):
        targetClass = Class()
        substitutionClass = Class()
        for t, s in sorted(subtable.mapping.items()):
            targetClass.append(t)
            substitutionClass.append(s)
        target = [Sequence([targetClass])]
        substitution = [Sequence([substitutionClass])]
        self.target = target
        self.substitution = substitution

    # type 2

    # type 3

    def _loadType3(self, subtable):
        target = []
        substitution = []
        for t, s in sorted(subtable.alternates.items()):
            # wrap it in a class
            t = Class([t])
            # wrap the class in a sequence
            t = Sequence([t])
            # store
            target.append(t)
            # wrap it in a class
            s = Class(s)
            # wrap the class in a sequence
            s = Sequence([s])
            # store
            substitution.append(s)
        self.target = target
        self.substitution = substitution

    # type 4

    def _loadType4(self, subtable):
        target = []
        substitution = []
        for firstGlyph, parts in sorted(subtable.ligatures.items()):
            for part in parts:
                # get the parts
                t = [firstGlyph] + part.Component
                # wrap the parts in classes
                t = [Class([i]) for i in t]
                # wrap the parts in a sequence
                t = Sequence(t)
                # store
                target.append(t)
                # get the substitution
                s = part.LigGlyph
                # wrap it in a class
                s = Class([s])
                # wrap the class in a sequence
                s = Sequence([s])
                # store
                substitution.append(s)
        self.target = target
        self.substitution = substitution

    # type 5

    # type 6

    def _loadType6(self, table, tableTag, subtable):
        assert subtable.Format == 3, "Stop being lazy."
        backtrack = [readCoverage(i) for i in reversed(subtable.BacktrackCoverage)]
        lookahead = [readCoverage(i) for i in subtable.LookAheadCoverage]
        input = [readCoverage(i) for i in subtable.InputCoverage]
        # the "ignore" rule generates subtables with an empty SubstLookup
        if not subtable.SubstLookupRecord:
            target = [Sequence(input)]
            substitution = []
        # a regular contextual rule
        else:
            target = []
            substitution = []
            assert len(subtable.SubstLookupRecord) == 1, "Does this ever happen?"
            for substLookup in subtable.SubstLookupRecord:
                index = substLookup.LookupListIndex
                lookupRecord = table.LookupList.Lookup[index]
                lookup = Lookup()
                lookup._load(table, tableTag, lookupRecord)
                # XXX potential problem here:
                # theoretically this nested lookup could have a flag that is
                # different than the flag of the lookup that contains this
                # subtable. i can't think of a way to do this with the
                # .fea syntax, so i'm not worrying about it right now.
                assert len(lookup.subtables) == 1, "Does this ever happen?"
                for sequenceIndex, targetSequence in enumerate(lookup.subtables[0].target):
                    substitutionSequence = lookup.subtables[0].substitution[sequenceIndex]
                    if lookup.type == 1:
                        assert len(input) == 1, "Does this ever happen?"
                        newTargetSequence = Sequence()
                        newSubstitutionSequence = Sequence()
                        for classIndex, targetClass in enumerate(targetSequence):
                            newTargetClass = Class()
                            newSubstitutionClass = Class()
                            for memberIndex, t in enumerate(targetClass):
                                if t in input[0]:
                                    newTargetClass.append(t)
                                    s = substitutionSequence[classIndex][memberIndex]
                                    newSubstitutionClass.append(s)
                            if newTargetClass:
                                newTargetSequence.append(newTargetClass)
                                newSubstitutionSequence.append(newSubstitutionClass)
                    elif lookup.type == 4:
                        if targetSequence != input:
                            print
                            print "GSUB question"
                            print targetSequence
                            print input
                            print
                        else:
                            newTargetSequence = targetSequence
                            newSubstitutionSequence = substitutionSequence
                    else:
                        raise NotImplementedError
                    target.append(newTargetSequence)
                    substitution.append(newSubstitutionSequence)
        self.backtrack = backtrack
        self.lookahead = lookahead
        self.target = target
        self.substitution = substitution

    # type 7

    # compression

    def _findPotentialClasses(self):
        candidates = []
        self._findPotentialClassesInSequence(self.backtrack, candidates)
        self._findPotentialClassesInSequence(self.lookahead, candidates)
        for sequence in self.target:
            self._findPotentialClassesInSequence(sequence, candidates)
        if self.type != 3:
            for sequence in self.substitution:
                self._findPotentialClassesInSequence(sequence, candidates)
        return candidates

    def _findPotentialClassesInSequence(self, sequence, candidates):
        for member in sequence:
            if member not in candidates:
                if len(member) > 1:
                    candidates.append(tuple(member))

    def _populateClasses(self, classes):
        self.backtrack = self._populateClassesInSequence(self.backtrack, classes)
        self.lookahead = self._populateClassesInSequence(self.lookahead, classes)
        self.target = [self._populateClassesInSequence(i, classes) for i in self.target]
        if self.type != 3:
            self.substitution = [self._populateClassesInSequence(i, classes) for i in self.substitution]

    def _populateClassesInSequence(self, sequence, classes):
        newSequence = Sequence()
        for member in sequence:
            member = tuple(member)
            if member in classes:
                classReference = ClassReference()
                classReference.name = classes[member]
                member = Class([classReference])
            newSequence.append(member)
        return newSequence

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False
        if self.backtrack != other.backtrack:
            return False
        if self.lookahead != other.lookahead:
            return False
        if self.target != other.target:
            return False
        if self.substitution != other.substitution:
            return False
        return True

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        s = "GSUBSubtable | type=%d backtrack=%s lookahead=%s target=%s substitution=%s" % (
            self.type,
            " ".join([str(i) for i in self.backtrack]),
            " ".join([str(i) for i in self.lookahead]),
            " ".join([str(i) for i in self.target]),
            " ".join([str(i) for i in self.substitution])
        )
        return hash(s)

    # manipulation

    def removeGlyphs(self, glyphNames):
        self._removeGlyphsFromSequence(self.backtrack, glyphNames)
        self._removeGlyphsFromSequence(self.lookahead, glyphNames)
        for sequence in self.target:
            self._removeGlyphsFromSequence(sequence, glyphNames)
        for sequence in self.substitution:
            self._removeGlyphsFromSequence(sequence, glyphNames)

    def _removeGlyphsFromSequence(self, sequence, glyphNames):
        for member in sequence:
            member.removeGlyphs(glyphNames)

    def renameGlyphs(self, glyphMapping):
        self._renameGlyphsInSequence(self.backtrack, glyphMapping)
        self._renameGlyphsInSequence(self.lookahead, glyphMapping)
        for sequence in self.target:
            self._renameGlyphsInSequence(sequence, glyphMapping)
        for sequence in self.substitution:
            self._renameGlyphsInSequence(sequence, glyphMapping)

    def _renameGlyphsInSequence(self, sequence, glyphMapping):
        for member in sequence:
            member.renameGlyphs(glyphMapping)

    def cleanup(self):
        pass


class Classes(dict):

    def removeGlyphs(self, glyphNames):
        for group in self.values():
            group.removeGlyphs(glyphNames)

    def renameGlyphs(self, glyphMapping):
        for group in self.values():
            group.renameGlyphs(glyphMapping)

    def cleanup(self):
        for className, members in self.items():
            if not members:
                del self[className]


class Sequence(list):

    def removeGlyphs(self, glyphNames):
        for group in self:
            group.removeGlyphs(glyphNames)

    def renameGlyphs(self, glyphMapping):
        for group in self:
            group.removeGlyphs(glyphMapping)

    def cleanup(self):
        new = []
        for group in self:
            group.cleanup()
            if group:
                new.append(group)
        del self[:]
        self.extend(new)


class Class(list):

    def removeGlyphs(self, glyphNames):
        new = [member for member in self if member not in glyphNames]
        if new != self:
            del self[:]
            self.extend(new)

    def renameGlyphs(self, glyphMapping):
        new = [glyphMapping.get(member, member) for member in self]
        if new != self:
            del self[:]
            self.extend(new)

    def cleanup(self):
        pass


class ClassReference(object):

    def __init__(self):
        self.name = None

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False
        return self.name == other.name

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        s = "ClassReference | name=%s" % self.name
        return hash(s)


# ---------
# Utilities
# ---------

def readCoverage(coverage):
    if not isinstance(coverage, list):
        coverage = coverage.glyphs
    coverage = Class(coverage)
    return coverage

def nameClass(features, members):
    name = "@" + "_".join(features)
    return name

def nameLookup(features):
    return "_".join(features)
